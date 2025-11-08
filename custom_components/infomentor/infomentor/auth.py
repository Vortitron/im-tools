"""Authentication handler for InfoMentor."""

import logging
import re
import json
import asyncio
import html
from typing import Optional, Dict, Any, List, Tuple
import aiohttp
from urllib.parse import urljoin as _urljoin

from .exceptions import InfoMentorAuthError, InfoMentorConnectionError

_LOGGER = logging.getLogger(__name__)

HUB_BASE_URL = "https://hub.infomentor.se"
MODERN_BASE_URL = "https://im.infomentor.se"
LEGACY_BASE_URL = "https://infomentor.se/swedish/production/mentor/"

# Request delay to be respectful to InfoMentor servers
REQUEST_DELAY = 0.3  # Reduced from 0.8s to 0.3s - mobile apps are typically faster

# Headers to mimic modern browser behaviour more closely
DEFAULT_HEADERS = {
	"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
	"Accept-Encoding": "gzip, deflate, br, zstd",
	"Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
	"Cache-Control": "no-cache",
	"Connection": "keep-alive",
	"Pragma": "no-cache",
	"Sec-Fetch-Dest": "document",
	"Sec-Fetch-Mode": "navigate",
	"Sec-Fetch-Site": "none",
	"Sec-Fetch-User": "?1",
	"Upgrade-Insecure-Requests": "1",
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
}


# Debug file paths
DEBUG_FILE_INITIAL = "/tmp/infomentor_debug_initial.html"
DEBUG_FILE_OAUTH = "/tmp/infomentor_debug_oauth.html"
DEBUG_FILE_DASHBOARD = "/tmp/infomentor_debug_dashboard.html"


async def _write_text_file_async(path: str, content: str) -> None:
	"""Write text to a file off the event loop to avoid blocking.

	This uses asyncio.to_thread to ensure file IO does not block the HA event loop.
	"""

	def _write():
		with open(path, 'w', encoding='utf-8') as f:
			f.write(content)

	try:
		await asyncio.to_thread(_write)
	except Exception as err:
		# Keep failures quiet at debug level to avoid noisy logs
		_LOGGER.debug(f"Could not save debug file {path}: {err}")


class _FormSubmissionResult:
	"""Internal helper to represent form submission outcomes."""

	def __init__(self, executed: bool, final_url: Optional[str] = None, final_text: Optional[str] = None) -> None:
		self.executed = executed
		self.final_url = final_url
		self.final_text = final_text


async def _auto_submit_openid_form(session: aiohttp.ClientSession, html: str, referer: str) -> _FormSubmissionResult:
	"""Detect and auto-submit OpenID/WS-Fed forms present in HTML.

	Returns _FormSubmissionResult with executed flag and last response data.
	"""
	try:
		import re as _re
		if 'id="openid_message"' not in html and 'id=\'openid_message\'' not in html:
			return _FormSubmissionResult(False)
		# Loop a few times in case of chained auto-submit forms
		current_html = html
		current_url = referer
		for _ in range(3):
			if 'id="openid_message"' not in current_html and 'id=\'openid_message\'' not in current_html:
				break
			# Extract form action
			action_match = _re.search(r'<form[^>]*id=["\']openid_message["\'][^>]*action=["\']([^"\']+)["\']', current_html, _re.IGNORECASE)
			action_url = action_match.group(1) if action_match else LEGACY_BASE_URL
			# Normalise relative action
			if action_url and not action_url.startswith('http'):
				action_url = _urljoin(current_url, action_url)
			# Extract hidden inputs
			inputs = {}
			for name, value in _re.findall(r'<input[^>]*type=["\']hidden["\'][^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']', current_html, _re.IGNORECASE):
				inputs[name] = value
			# Post the form
			headers = DEFAULT_HEADERS.copy()
			headers.update({
				"Content-Type": "application/x-www-form-urlencoded",
				"Origin": HUB_BASE_URL if "infomentor.se" not in action_url else "https://infomentor.se",
				"Referer": current_url,
				"Sec-Fetch-Site": "cross-site" if "hub.infomentor.se" in current_url and "infomentor.se" in action_url else "same-origin",
				"Sec-Fetch-Dest": "document",
			})
			from urllib.parse import urlencode as _urlencode
			await asyncio.sleep(REQUEST_DELAY)
			async with session.post(action_url, headers=headers, data=_urlencode(inputs), allow_redirects=True) as resp:
				current_html = await resp.text()
				current_url = str(resp.url)
				_LOGGER.debug(f"Auto-submitted OpenID form to {action_url}; status={resp.status}, final_url={resp.url}")
		return _FormSubmissionResult(True, current_url, current_html)
	except Exception as e:
		_LOGGER.debug(f"Auto-submit OpenID form handling failed: {e}")
		return _FormSubmissionResult(False)


def _choose_best_school_option(
	options: List[Tuple[str, str]],
	stored_url: Optional[str],
	stored_name: Optional[str],
	username: Optional[str],
) -> Tuple[Optional[Tuple[str, str]], List[Tuple[str, str, int, int]]]:
	"""Choose the most suitable school option based on stored data and heuristics."""
	if not options:
		return (None, [])

	if stored_url:
		for idx, (title, url) in enumerate(options):
			if url == stored_url:
				return ((title, url), [(title, url, 1000, idx)])

	username_clues: List[str] = []
	if username:
		username_lower = username.lower()
		if '@' in username_lower:
			domain = username_lower.split('@', 1)[1].strip()
			generic_domains = {
				"gmail.com",
				"hotmail.com",
				"outlook.com",
				"icloud.com",
				"me.com",
				"mac.com",
				"yahoo.com",
				"protonmail.com",
				"live.com",
				"msn.com",
			}
			if domain and domain not in generic_domains:
				username_clues.append(domain)
				primary = domain.split('.')[0]
				if primary and len(primary) >= 3 and primary not in username_clues:
					username_clues.append(primary)
				for part in domain.replace('.', ' ').replace('-', ' ').split():
					part = part.strip()
					if part and len(part) >= 3 and part not in username_clues:
						username_clues.append(part)

	scored: List[Tuple[int, int, str, str]] = []
	for idx, (title, url) in enumerate(options):
		lower_title = title.lower()
		lower_url = url.lower()
		score = 0

		if stored_name and stored_name.lower() == lower_title:
			score += 900
		if 'infomentor' in lower_title:
			score += 120
		if 'info mentor' in lower_title:
			score += 30
		if 'övrigt' in lower_title or 'ovrigt' in lower_title:
			score += 40
		if 'sso test' in lower_title:
			score += 30
		if 'sso' in lower_title:
			score += 20
		if 'elever' in lower_title or 'student' in lower_title or 'students' in lower_title:
			score += 12
		if 'pupil' in lower_title:
			score += 10
		if 'skola' in lower_title or 'school' in lower_title:
			score += 8
		if 'kommun' in lower_title:
			score += 6
		if 'barn' in lower_title:
			score += 4
		if 'förskola' in lower_title or 'forskola' in lower_title:
			score += 2

		if 'ims-' in lower_url or 'ims_' in lower_url:
			score += 140
		if 'login/initial' in lower_url:
			score += 100
		if 'communeid' in lower_url:
			score += 60
		if 'infomentor.se' in lower_url:
			score += 40
		if 'sso.infomentor.se/login.ashx' in lower_url:
			score += 25
		if 'login.ashx?idp=' in lower_url:
			score += 15
		if lower_url.startswith('https://idp') or '://idp' in lower_url:
			score -= 20
		if 'idp' in lower_url and 'infomentor.se' not in lower_url:
			score -= 10
		if 'chooseauthmech' in lower_url:
			score -= 4

		matched_clue = False
		for clue in username_clues:
			if not clue:
				continue
			if clue in lower_url:
				score += 260
				matched_clue = True
			elif clue in lower_title:
				score += 180
				matched_clue = True

		if username_clues and not matched_clue:
			score -= 400

		scored.append((score, idx, title, url))

	if not scored:
		return (None, [])

	ranked = sorted(scored, key=lambda item: (item[0], item[1]))
	ranked_desc = list(reversed(ranked))
	best_score, best_idx, best_title, best_url = ranked_desc[0]
	debug_scores = [(title, url, score, order) for score, order, title, url in ranked_desc]
	return ((best_title, best_url), debug_scores)


class InfoMentorAuth:
	"""Handles authentication with InfoMentor system."""
	
	def __init__(self, session: aiohttp.ClientSession, storage=None):
		"""Initialise authentication handler.
		
		Args:
			session: aiohttp session to use for requests
			storage: Optional storage for persisting school selection
		"""
		self.session = session
		self.storage = storage
		self.authenticated = False
		self.pupil_ids: list[str] = []
		self.pupil_names: dict[str, str] = {}  # Maps pupil_id -> pupil_name
		self.pupil_switch_ids: dict[str, str] = {}  # Maps pupil_id -> switch_id
		self._last_auth_time: Optional[float] = None
		self._auth_cookies_backup: Optional[Dict[str, str]] = None
		self._username: Optional[str] = None
		self._password: Optional[str] = None
		
	def _backup_auth_cookies(self) -> None:
		"""Backup authentication cookies for potential restoration."""
		if self.session.cookie_jar:
			self._auth_cookies_backup = {}
			for cookie in self.session.cookie_jar:
				try:
					# Check if this is an InfoMentor-related cookie
					domain = str(cookie.get('domain', '')) if hasattr(cookie, 'get') else str(getattr(cookie, 'domain', ''))
					if any(infomentor_domain in domain for infomentor_domain in ['infomentor.se', '.infomentor.se']):
						# Handle different cookie formats safely
						cookie_name = None
						cookie_value = None
						
						# Try multiple ways to get the cookie name
						if hasattr(cookie, 'get'):
							cookie_name = cookie.get('name') or cookie.get('key')
						else:
							cookie_name = getattr(cookie, 'name', None) or getattr(cookie, 'key', None)
						
						# Try multiple ways to get the cookie value
						if hasattr(cookie, 'get'):
							cookie_value = cookie.get('value')
						else:
							cookie_value = getattr(cookie, 'value', None)
						
						# If we still don't have a value, try converting the whole cookie to string
						if not cookie_value:
							cookie_value = str(cookie)
						
						if cookie_name and cookie_value and cookie_name != cookie_value:
							self._auth_cookies_backup[cookie_name] = cookie_value
				except (KeyError, AttributeError, TypeError) as e:
					_LOGGER.debug(f"Skipping problematic cookie during backup: {e}")
					continue
			
			_LOGGER.debug(f"Backed up {len(self._auth_cookies_backup)} auth cookies")
		else:
			_LOGGER.debug("No cookie jar available for backup")
	
	def _restore_auth_cookies(self) -> bool:
		"""Attempt to restore authentication cookies."""
		if not self._auth_cookies_backup:
			return False
		
		try:
			for name, value in self._auth_cookies_backup.items():
				self.session.cookie_jar.update_cookies({name: value}, response_url=HUB_BASE_URL)
			_LOGGER.debug("Restored authentication cookies")
			return True
		except Exception as e:
			_LOGGER.warning(f"Failed to restore auth cookies: {e}")
			return False
	
	def is_auth_likely_expired(self) -> bool:
		"""Check if authentication is likely expired based on time and session state."""
		if not self.authenticated or not self._last_auth_time:
			return True
		
		# Check if authentication is older than 8 hours (typical session timeout)
		import time
		if time.time() - self._last_auth_time > 8 * 3600:
			_LOGGER.debug("Authentication likely expired due to age")
			return True
		
		# Check if we have essential cookies
		if not self.session.cookie_jar:
			_LOGGER.debug("No cookie jar available")
			return True
		
		essential_cookies = ['ASP.NET_SessionId', '.ASPXAUTH']
		found_cookies = []
		for cookie in self.session.cookie_jar:
			try:
				name = cookie.get('name', '') if hasattr(cookie, 'get') else getattr(cookie, 'name', getattr(cookie, 'key', ''))
				if name in essential_cookies:
					found_cookies.append(name)
			except (KeyError, AttributeError, TypeError):
				# Skip problematic cookies
				continue
		
		if not found_cookies:
			_LOGGER.debug("No essential authentication cookies found")
			return True
		
		return False
	
	async def login(self, username: str, password: str) -> bool:
		"""Authenticate with InfoMentor using OAuth flow.
		
		Args:
			username: Username or email
			password: Password
			
		Returns:
			True if authentication successful
		"""
		_LOGGER.error("*** LOGIN METHOD CALLED v0.0.53 *** username=%s", username)
		try:
			_LOGGER.info("Starting InfoMentor OAuth authentication flow!!")
			# Store for potential reauthentication
			self._username = username
			self._password = password
			
			# Step 1: Get OAuth token (primary method, confirmed by user)
			_LOGGER.error("*** STEP 1 STARTING - Getting OAuth token v0.0.53 ***")
			try:
				oauth_token = await self._get_oauth_token()
				_LOGGER.error(f"*** OAUTH TOKEN RESULT v0.0.53 *** token={oauth_token[:20] if oauth_token else 'None'}...")
				
				if oauth_token:
					_LOGGER.error("*** STEP 2 STARTING - OAuth completion v0.0.53 ***")
					await self._complete_oauth_to_modern_domain(oauth_token, username, password)
					_LOGGER.error("*** STEP 2 COMPLETED v0.0.53 ***")
				else:
					_LOGGER.error("*** NO OAUTH TOKEN - Trying direct login fallback v0.0.53 ***")
					await self._direct_login_with_credentials(username, password)
			except Exception as oauth_err:
				_LOGGER.error(f"*** OAUTH FLOW FAILED v0.0.53 *** error={oauth_err}")
				_LOGGER.error("*** FALLBACK - Trying direct login v0.0.53 ***")
				
				# Fallback to direct login if OAuth fails
				try:
					await self._direct_login_with_credentials(username, password)
					_LOGGER.error("*** DIRECT LOGIN FALLBACK COMPLETED v0.0.53 ***")
				except Exception as fallback_err:
					_LOGGER.error(f"*** ALL LOGIN METHODS FAILED v0.0.53 *** oauth_err={oauth_err}, fallback_err={fallback_err}")
					raise oauth_err  # Prefer to show OAuth error since that's the primary method
			
			# Step 3: Get pupil IDs from modern interface
			_LOGGER.info("Step 3: Getting pupil IDs from dashboard")
			self.pupil_ids = await self._get_pupil_ids_modern()
			
			# Step 4: Get switch ID mappings
			_LOGGER.info("Step 4: Building switch ID mappings")
			await self._build_switch_id_mapping()
			
			if not self.pupil_ids:
				_LOGGER.warning("No pupil IDs found - authentication may have failed or account has no pupils")
				# Try a final verification to see if we're actually authenticated
				await self._verify_authentication_status()
				
				# Don't mark as authenticated if we have no pupil IDs
				# This forces re-authentication on the next attempt
				_LOGGER.error("*** AUTHENTICATION FAILED - NO PUPIL IDS FOUND v0.0.40 ***")
				self.authenticated = False
				raise InfoMentorAuthError("Authentication failed - no pupil IDs found")
			else:
				_LOGGER.info(f"*** AUTHENTICATION SUCCESS v0.0.40 *** - {len(self.pupil_ids)} pupils")
				# Mark as authenticated and track timing
				self.authenticated = True
				import time
				self._last_auth_time = time.time()
				
				# Backup authentication cookies for potential restoration
				self._backup_auth_cookies()
			
			_LOGGER.info("Authentication completed successfully")
			return True
			
		except InfoMentorAuthError:
			# Re-raise authentication errors as-is
			raise
		except aiohttp.ClientError as e:
			raise InfoMentorConnectionError(f"Connection error: {e}") from e
		except Exception as e:
			_LOGGER.error(f"Authentication failed: {e}")
			raise InfoMentorAuthError(f"Authentication failed: {e}") from e

	async def _login_via_login_page(self, username: str, password: str) -> None:
		"""Attempt to authenticate by starting from the explicit login page.

		Handles auto-submit OpenID forms and credential forms without requiring a prior oauth_token.
		"""
		headers = DEFAULT_HEADERS.copy()
		login_url = f"{HUB_BASE_URL}/Authentication/Authentication/Login?apiType=IM1&forceOAuth=true"
		last_text = ""
		last_url = login_url
		# Visit login page
		await asyncio.sleep(REQUEST_DELAY)
		async with self.session.get(login_url, headers=headers, allow_redirects=True) as resp:
			last_text = await resp.text()
			last_url = str(resp.url)
			_LOGGER.debug(f"Login page status={resp.status}, url={last_url}")
		# Handle auto-submit if present
		if ('id="openid_message"' in last_text) or ('id=\'openid_message\'' in last_text):
			_LOGGER.debug("Auto-submit form detected on login page; submitting...")
			result = await _auto_submit_openid_form(self.session, last_text, referer=last_url)
			if result.executed:
				last_text = result.final_text or last_text
				last_url = result.final_url or last_url
		# If a credential form is present, submit credentials
		if any(key in last_text.lower() for key in ['txtnotandanafn', 'txtlykilord']):
			await self._submit_credentials_and_handle_second_oauth(last_text, username, password, last_url)
			return
		# If an oauth_token appears, submit second token
		second_oauth_match = re.search(r'oauth_token"\s+value="([\w+=/]+)"', last_text)
		if second_oauth_match:
			await self._submit_second_oauth_token(second_oauth_match.group(1))
			return
		# Otherwise, verify status; some flows may have completed
		await self._verify_authentication_status()
	
	async def _get_oauth_token(self) -> Optional[str]:
		"""Get OAuth token from initial OAuth endpoint."""
		_LOGGER.info("*** STARTING OAUTH TOKEN EXTRACTION v0.0.39 ***")
		
		# Get OAuth token from the OAuth login endpoint
		oauth_url = f"{HUB_BASE_URL}/Authentication/Authentication/Login?apiType=IM1&forceOAuth=true&apiInstance="
		headers = DEFAULT_HEADERS.copy()
		await asyncio.sleep(REQUEST_DELAY)  # Be respectful to the server
		
		try:
			async with self.session.get(oauth_url, headers=headers, allow_redirects=True) as resp:
				_LOGGER.info(f"OAuth request to {oauth_url} returned status: {resp.status}")
				_LOGGER.info(f"Final URL: {resp.url}")
				
				text = await resp.text()
				_LOGGER.info(f"Response content length: {len(text)}")
				
				# Save initial response for debugging
				await _write_text_file_async(DEBUG_FILE_INITIAL, text)
				_LOGGER.info(f"Saved initial OAuth response to {DEBUG_FILE_INITIAL}")
				
				# Look for OAuth token in the response
				oauth_token = None
				
				# First check if we got an auto-submit form with OAuth token
				if 'id="openid_message"' in text:
					_LOGGER.info("Found auto-submit form in initial response")
					# Extract OAuth token from hidden input
					oauth_match = re.search(r'<input[^>]*name=["\']oauth_token["\'][^>]*value=["\']([^"\']+)["\']', text, re.IGNORECASE)
					if oauth_match:
						oauth_token = oauth_match.group(1)
						_LOGGER.info(f"Found OAuth token in form: {oauth_token[:20]}...")
						
						# Auto-submit this form to get to the credential page
						_LOGGER.info("Auto-submitting initial OAuth form...")
						form_result = await _auto_submit_openid_form(self.session, text, str(resp.url))
						if form_result.executed:
							_LOGGER.info("Auto-submitted initial OAuth form successfully")
							# The form submission result is not needed for the OAuth token extraction
						else:
							_LOGGER.error("Failed to auto-submit initial OAuth form")
				
				# If no OAuth token found in form, try URL patterns
				if not oauth_token:
					oauth_match = re.search(r'oauth_token=([^&"\']+)', text)
					if oauth_match:
						oauth_token = oauth_match.group(1)
						_LOGGER.info(f"Found OAuth token in URL: {oauth_token[:20]}...")
				
				if not oauth_token:
					_LOGGER.error("Could not find OAuth token in response")
					# Log a short snippet of the server response for diagnostics
					try:
						_LOGGER.error(f"OAuth response (truncated): {text[:500]}...")
					except Exception:
						pass
					return None
				
				_LOGGER.info(f"Successfully extracted OAuth token: {oauth_token[:20]}...")
				return oauth_token
			
		except Exception as e:
			_LOGGER.error(f"Exception during OAuth token extraction: {e}")
			raise
	
	async def _complete_oauth_to_modern_domain(self, oauth_token: str, username: str, password: str) -> None:
		"""Complete OAuth flow with improved LoginCallback handling."""
		try:
			_LOGGER.error("*** STARTING ENHANCED OAUTH COMPLETION v0.0.53 ***")
			
			# Stage 1: Submit initial OAuth token to get credential form
			headers = DEFAULT_HEADERS.copy()
			headers.update({
				"Content-Type": "application/x-www-form-urlencoded",
				"Origin": HUB_BASE_URL,
				"Referer": f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true",
				"Sec-Fetch-Site": "cross-site",
				"Sec-Fetch-Dest": "document",
			})
			
			oauth_data = f"oauth_token={oauth_token}"
			_LOGGER.error(f"*** POSTING OAUTH TOKEN v0.0.53 *** to {LEGACY_BASE_URL}")
			
			await asyncio.sleep(REQUEST_DELAY)  # Be respectful to the server
			async with self.session.post(
				LEGACY_BASE_URL,
				headers=headers,
				data=oauth_data,
				allow_redirects=True
			) as resp:
				stage1_text = await resp.text()
				_LOGGER.error(f"*** STAGE 1 RESPONSE v0.0.53 *** status={resp.status} url={resp.url}")
				_LOGGER.error(f"*** STAGE 1 LENGTH v0.0.53 *** {len(stage1_text)} chars")
				
				# Save stage 1 response for debugging
				await _write_text_file_async(DEBUG_FILE_OAUTH, stage1_text)
				_LOGGER.error(f"*** SAVED OAUTH DEBUG FILE v0.0.53 *** {DEBUG_FILE_OAUTH}")
				
				# Check if we already got a LoginCallback redirect
				if "LoginCallback" in str(resp.url):
					_LOGGER.error("*** RECEIVED EARLY LOGINCALLBACK v0.0.53 ***")
					await self._handle_login_callback(str(resp.url), stage1_text)
					return
			
			# Some flows render auto-submit form here; handle it
			if ('id="openid_message"' in stage1_text) or ('id=\'openid_message\'' in stage1_text):
				_LOGGER.info("Detected auto-submit form during stage 1; submitting...")
				result = await _auto_submit_openid_form(self.session, stage1_text, referer=str(resp.url))
				if result.executed:
					stage1_text = result.final_text or stage1_text
					_LOGGER.info("Stage 1 auto-submit form completed")
					
					# Check if auto-submit led to LoginCallback
					if result.final_url and "LoginCallback" in result.final_url:
						_LOGGER.error("*** AUTO-SUBMIT LED TO LOGINCALLBACK v0.0.53 ***")
						await self._handle_login_callback(result.final_url, stage1_text)
						return
				else:
					_LOGGER.error("Stage 1 auto-submit form failed")
			
			# Check for school selection page
			_LOGGER.info(f"*** CHECKING FOR SCHOOL SELECTION v0.0.53 *** IdpListRepeater: {'IdpListRepeater' in stage1_text}, elever: {'elever' in stage1_text}")
			if "IdpListRepeater" in stage1_text and ("elever" in stage1_text or "kommun" in stage1_text):
				_LOGGER.error("*** DETECTED SCHOOL SELECTION PAGE v0.0.53 ***")
				original_stage1_text = stage1_text  # Keep the original in case school selection fails
				
				try:
					await self._handle_school_selection(stage1_text, str(resp.url))
					# Re-fetch to get the credential form after school selection
					await asyncio.sleep(REQUEST_DELAY)
					async with self.session.get(str(resp.url), headers=DEFAULT_HEADERS) as resp2:
						stage1_text = await resp2.text()
						_LOGGER.error(f"*** RE-FETCHED AFTER SCHOOL SELECTION v0.0.53 *** {resp2.status}")
						
						# Check if school selection led to LoginCallback
						if "LoginCallback" in str(resp2.url):
							_LOGGER.error("*** SCHOOL SELECTION LED TO LOGINCALLBACK v0.0.53 ***")
							await self._handle_login_callback(str(resp2.url), stage1_text)
							return
				except Exception as school_err:
					_LOGGER.error(f"*** SCHOOL SELECTION FLOW FAILED v0.0.53 *** {school_err}")
					_LOGGER.error("*** USING ORIGINAL STAGE1 TEXT FOR CREDENTIALS v0.0.53 ***")
					stage1_text = original_stage1_text  # Fall back to original response
			else:
				_LOGGER.error("*** NO SCHOOL SELECTION PAGE DETECTED v0.0.53 ***")
			
			# Check if we need to submit credentials
			_LOGGER.error(f"*** CHECKING FOR CREDENTIALS v0.0.53 *** txtnotandanafn: {'txtnotandanafn' in stage1_text.lower()}, txtlykilord: {'txtlykilord' in stage1_text.lower()}")
			if any(field in stage1_text.lower() for field in ['txtnotandanafn', 'txtlykilord']):
				_LOGGER.error("*** FOUND CREDENTIAL FORM - SUBMITTING v0.0.53 ***")
				
				# Extract and submit credentials
				await self._submit_credentials_and_handle_second_oauth(stage1_text, username, password, str(resp.url))
				_LOGGER.error("*** CREDENTIAL SUBMISSION COMPLETED v0.0.53 ***")
			else:
				_LOGGER.error("*** NO CREDENTIAL FORM FOUND v0.0.53 ***")
				_LOGGER.error(f"*** STAGE 1 SNIPPET v0.0.53 *** {stage1_text[:500]}...")
		except Exception as oauth_completion_err:
			_LOGGER.error(f"*** OAUTH COMPLETION EXCEPTION v0.0.53 *** {oauth_completion_err}")
			raise
	
	async def _handle_login_callback(self, callback_url: str, response_text: str) -> None:
		"""Handle LoginCallback URL with oauth_token and oauth_verifier."""
		from urllib.parse import urlparse, parse_qs
		
		_LOGGER.error(f"*** HANDLING LOGINCALLBACK v0.0.53 *** {callback_url}")
		
		# Parse the callback URL to extract OAuth parameters
		parsed_url = urlparse(callback_url)
		query_params = parse_qs(parsed_url.query)
		
		oauth_token = query_params.get('oauth_token', [None])[0]
		oauth_verifier = query_params.get('oauth_verifier', [None])[0]
		
		_LOGGER.error(f"*** CALLBACK OAUTH TOKEN v0.0.53 *** {oauth_token[:20] if oauth_token else 'None'}...")
		_LOGGER.error(f"*** CALLBACK OAUTH VERIFIER v0.0.53 *** {oauth_verifier[:20] if oauth_verifier else 'None'}...")
		
		if not oauth_token or not oauth_verifier:
			_LOGGER.error("*** INCOMPLETE OAUTH CALLBACK - MISSING TOKEN OR VERIFIER v0.0.53 ***")
			return
		
		# Save the callback response for debugging
		await _write_text_file_async("/tmp/infomentor_oauth_callback.html", response_text)
		_LOGGER.error("*** SAVED OAUTH CALLBACK DEBUG FILE v0.0.53 ***")
		
		# Check if the callback response already contains pupil data
		if any(indicator in response_text.lower() for indicator in ['pupil', 'elev', 'student', 'dashboard']):
			_LOGGER.error("*** CALLBACK CONTAINS PUPIL DATA v0.0.53 ***")
		else:
			_LOGGER.error("*** CALLBACK REQUIRES ADDITIONAL PROCESSING v0.0.53 ***")
			
			# Try to navigate to the dashboard using the callback parameters
			await self._navigate_to_dashboard_with_oauth_params(oauth_token, oauth_verifier)
	
	async def _navigate_to_dashboard_with_oauth_params(self, oauth_token: str, oauth_verifier: str) -> None:
		"""Navigate to dashboard using OAuth token and verifier."""
		_LOGGER.error("*** NAVIGATING TO DASHBOARD WITH OAUTH PARAMS v0.0.53 ***")
		
		# Common dashboard URLs to try
		dashboard_urls = [
			f"https://infomentor.se/Swedish/Production/mentor/",
			f"https://hub.infomentor.se/",
			f"https://hub.infomentor.se/home",
		]
		
		headers = DEFAULT_HEADERS.copy()
		headers["Referer"] = f"{HUB_BASE_URL}/Authentication/Authentication/LoginCallback"
		
		for dashboard_url in dashboard_urls:
			try:
				_LOGGER.error(f"*** TRYING DASHBOARD URL v0.0.53 *** {dashboard_url}")
				async with self.session.get(dashboard_url, headers=headers, allow_redirects=True) as resp:
					dashboard_text = await resp.text()
					_LOGGER.error(f"*** DASHBOARD RESPONSE v0.0.53 *** {resp.status} -> {resp.url}")
					
					# Check if this contains pupil data
					if any(indicator in dashboard_text.lower() for indicator in ['pupil', 'elev', 'student']):
						_LOGGER.error("*** FOUND PUPIL DATA IN DASHBOARD v0.0.53 ***")
						await _write_text_file_async("/tmp/infomentor_oauth_dashboard.html", dashboard_text)
						break
					elif "login" in dashboard_text.lower() or "authentication" in dashboard_text.lower():
						_LOGGER.error("*** DASHBOARD REQUIRES ADDITIONAL AUTH v0.0.53 ***")
						continue
					else:
						_LOGGER.error("*** DASHBOARD STATUS UNCLEAR v0.0.53 ***")
						
			except Exception as e:
				_LOGGER.error(f"*** DASHBOARD NAVIGATION ERROR v0.0.53 *** {e}")
				continue
	
	async def _submit_credentials_and_handle_second_oauth(self, form_html: str, username: str, password: str, form_url: str) -> None:
		"""Submit credentials and handle the second OAuth token."""
		_LOGGER.debug("Submitting credentials for two-stage OAuth")
		
		# Extract form fields
		form_data = {}
		
		# ViewState fields for ASP.NET
		for field in ['__VIEWSTATE', '__VIEWSTATEGENERATOR', '__EVENTVALIDATION']:
			pattern = f'{field}["\'][^>]*value=["\']([^"\']+)["\']'
			match = re.search(pattern, form_html)
			if match:
				form_data[field] = match.group(1)
		
		# Set form submission fields
		form_data.update({
			'__EVENTTARGET': 'login_ascx$btnLogin',
			'__EVENTARGUMENT': '',
			'login_ascx$txtNotandanafn': username,
			'login_ascx$txtLykilord': password,
		})
		
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Content-Type": "application/x-www-form-urlencoded",
			"Origin": "https://infomentor.se",
			"Referer": form_url,
			"Sec-Fetch-Site": "same-origin",
			"Sec-Fetch-Dest": "document",
		})
		
		from urllib.parse import urlencode
		
		await asyncio.sleep(REQUEST_DELAY)  # Be respectful to the server
		async with self.session.post(
			form_url,
			headers=headers,
			data=urlencode(form_data),
			allow_redirects=True
		) as resp:
			cred_text = await resp.text()
			_LOGGER.error(f"*** CREDENTIALS RESPONSE v0.0.53 *** status={resp.status} url={resp.url}")
			
			# Check if credentials led to LoginCallback
			if "LoginCallback" in str(resp.url):
				_LOGGER.error("*** CREDENTIALS LED TO LOGINCALLBACK v0.0.53 ***")
				await self._handle_login_callback(str(resp.url), cred_text)
				return
			
			# Check for credential rejection first
			if "login_ascx" in cred_text.lower() and "txtnotandanafn" in cred_text.lower():
				# If we still see the login form, credentials were likely rejected
				_LOGGER.error("Credentials appear to have been rejected")
				# Log a truncated snippet to aid debugging
				try:
					_LOGGER.error(f"Credentials rejection response (truncated): {cred_text[:500]}...")
				except Exception:
					pass
				raise InfoMentorAuthError("Invalid credentials - login form still present after submission")
			
			# Look for second OAuth token in the response
			second_oauth_match = re.search(r'oauth_token"\s+value="([\w+=/]+)"', cred_text)
			if second_oauth_match:
				second_oauth_token = second_oauth_match.group(1)
				_LOGGER.error(f"*** FOUND SECOND OAUTH TOKEN v0.0.53 *** {second_oauth_token[:10]}...")
				
				# Submit the second OAuth token
				await self._submit_second_oauth_token(second_oauth_token)
			else:
				_LOGGER.error("*** NO SECOND OAUTH TOKEN v0.0.53 *** - checking authentication state")
				
				# Check for signs of successful authentication
				success_indicators = [
					"default.aspx" in str(resp.url).lower(),
					"hub.infomentor.se" in str(resp.url).lower(),
					"logout" in cred_text.lower(),
					"dashboard" in cred_text.lower()
				]
				
				if any(success_indicators):
					_LOGGER.error("*** CREDENTIALS ACCEPTED WITHOUT SECOND OAUTH v0.0.53 ***")
				else:
					_LOGGER.error("*** UNCLEAR AUTHENTICATION STATE v0.0.53 ***")
					# Continue anyway as the authentication might still work
	
	async def _submit_second_oauth_token(self, oauth_token: str) -> None:
		"""Submit the second OAuth token to complete authentication."""
		_LOGGER.debug("Submitting second OAuth token")
		
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Content-Type": "application/x-www-form-urlencoded",
			"Origin": HUB_BASE_URL,
			"Referer": f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true",
			"Sec-Fetch-Site": "same-site",
			"Sec-Fetch-Dest": "document",
		})
		
		oauth_data = f"oauth_token={oauth_token}"
		
		async with self.session.post(
			LEGACY_BASE_URL,
			headers=headers,
			data=oauth_data,
			allow_redirects=True
		) as resp:
			final_text = await resp.text()
			_LOGGER.error(f"*** SECOND OAUTH RESPONSE v0.0.53 *** {resp.status}, URL: {resp.url}")
			
			# Check if second OAuth led to LoginCallback
			if "LoginCallback" in str(resp.url):
				_LOGGER.error("*** SECOND OAUTH LED TO LOGINCALLBACK v0.0.53 ***")
				await self._handle_login_callback(str(resp.url), final_text)
				return
			
			# More robust authentication verification
			auth_success_indicators = [
				"default.aspx" in str(resp.url).lower(),  # Successfully redirected to main page
				"hub.infomentor.se" in str(resp.url),  # Redirected to hub
				"dashboard" in final_text.lower(),
				"logout" in final_text.lower(),
				"pupil" in final_text.lower(),
				"elev" in final_text.lower()
			]
			
			auth_failure_indicators = [
				"login_ascx" in final_text.lower(),
				"txtnotandanafn" in final_text.lower(),
				"txtlykilord" in final_text.lower(),
				"invalid" in final_text.lower(),
				"fel" in final_text.lower()  # Swedish for "error"
			]
			
			# Check for positive indicators first
			if any(auth_success_indicators):
				_LOGGER.debug("Two-stage OAuth completed successfully - found success indicators")
				# Touch modern root to ensure cookies are set on modern domain too
				try:
					headers2 = DEFAULT_HEADERS.copy()
					headers2["Referer"] = f"{HUB_BASE_URL}/"
					async with self.session.get(f"{MODERN_BASE_URL}/", headers=headers2, allow_redirects=True) as modern_resp:
						_LOGGER.debug(f"Touched modern root, status={modern_resp.status}")
				except Exception as e_touch:
					_LOGGER.debug(f"Touching modern root failed: {e_touch}")
				return
			
			# Check for negative indicators
			if any(auth_failure_indicators):
				_LOGGER.warning("Two-stage OAuth may not have completed fully - found failure indicators")
				# Log a truncated snippet to aid debugging
				try:
					_LOGGER.warning(f"Second OAuth response (truncated): {final_text[:500]}...")
				except Exception:
					pass
				# Try to verify by making a test request to the hub
				await self._verify_authentication_status()
			else:
				_LOGGER.debug("Two-stage OAuth status unclear - attempting verification")
				await self._verify_authentication_status()
	
	async def _handle_school_selection(self, html: str, referer: str) -> None:
		"""Handle automatic school/municipality selection."""
		_LOGGER.info("*** PROCESSING SCHOOL SELECTION v0.0.90 ***")
		
		import re as _re
		
		# First, check if we have a previously selected school preference
		stored_school_url = None
		stored_school_name = None
		if self.storage:
			try:
				stored_school_url, stored_school_name = await self.storage.get_selected_school_details()
				if stored_school_url or stored_school_name:
					_LOGGER.info(f"*** FOUND STORED SCHOOL PREFERENCE v0.0.90 *** url={stored_school_url} name={stored_school_name}")
			except Exception as e:
				_LOGGER.debug(f"Could not load stored school preference: {e}")
		
		# Extract all school options from the selection page
		# Look for input fields with URLs and their corresponding titles
		url_pattern = r'<input[^>]*name=["\']login_ascx\$IdpListRepeater\$ctl(\d+)\$url["\'][^>]*value=["\']([^"\']*)["\']'
		url_matches = _re.findall(url_pattern, html, _re.IGNORECASE)
		
		_LOGGER.error(f"*** FOUND {len(url_matches)} SCHOOL OPTIONS v0.0.76 ***")
		
		# Save school selection page for debugging
		await _write_text_file_async("/tmp/infomentor_school_selection.html", html)
		_LOGGER.error("*** SAVED SCHOOL SELECTION PAGE v0.0.76 *** /tmp/infomentor_school_selection.html")
		
		# Log all available schools for debugging
		all_schools: List[Tuple[str, str]] = []
		for control_id, url in url_matches:
			title_pattern = f'<span[^>]*id=["\']login_ascx_IdpListRepeater_ctl{control_id}_title["\'][^>]*>([^<]+)</span>'
			title_match = _re.search(title_pattern, html, _re.IGNORECASE)
			if title_match:
				import html as html_module
				raw_title = title_match.group(1).strip()
				title = html_module.unescape(raw_title)
				decoded_url = html_module.unescape(url.strip())
				all_schools.append((title, decoded_url))
				_LOGGER.error(f"*** AVAILABLE SCHOOL v0.0.90 *** [{control_id}]: '{title}' -> {decoded_url}")
		
		selected_option, scored_options = _choose_best_school_option(
			all_schools,
			stored_school_url,
			stored_school_name,
			self._username,
		)
		
		if scored_options:
			for rank, (title, url, score, order) in enumerate(scored_options[:5], start=1):
				_LOGGER.error(f"*** SCHOOL SCORECARD v0.0.90 *** rank={rank} score={score} order={order} '{title}' -> {url}")
		
		if not selected_option:
			_LOGGER.warning("No suitable school found in selection page")
			return
		
		school_name, school_url = selected_option
		_LOGGER.info(f"*** CHOSEN SCHOOL v0.0.90 *** {school_name} -> {school_url}")
		
		# Navigate to the selected school's authentication URL
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Referer": referer,
		})
		
		# Save the selected school for future use
		if self.storage and school_url and school_name:
			try:
				await self.storage.save_selected_school_url(school_url, school_name)
			except Exception as e:
				_LOGGER.debug(f"Could not save selected school: {e}")
		
		try:
			await asyncio.sleep(REQUEST_DELAY)
			_LOGGER.error(f"*** ATTEMPTING SCHOOL SELECTION v0.0.75 *** {school_name} -> {school_url}")
			
			# Try with a shorter timeout and better error handling
			timeout = aiohttp.ClientTimeout(total=10)
			async with self.session.get(school_url, headers=headers, allow_redirects=True, timeout=timeout) as resp:
				_LOGGER.error(f"*** SCHOOL SELECTION SUCCESS v0.0.75 *** {resp.status} -> {resp.url}")
				selection_text = await resp.text()
				
				# Handle authentication method selection page immediately
				_LOGGER.error(f"*** AUTH METHOD CHECK v0.0.47 *** chooseAuthmech: {'chooseAuthmech' in str(resp.url)}")
				_LOGGER.error(f"*** PAGE CONTENT SAMPLE v0.0.47 *** {selection_text[:1000]}...")
				_LOGGER.error(f"*** PAGE CONTENT LENGTH v0.0.47 *** {len(selection_text)} chars")
				
				# Check for multiple possible authentication method texts in the complete content
				auth_method_indicators = [
					"Lösenord",          # Swedish
					"Password",          # English  
					"L%C3%B6senord",     # URL encoded
					"L&#246;senord",     # HTML entity encoded
					"L&#37;c3&#37;b6senord", # Double URL encoded  
					"lösenord",          # Lowercase
					"password",          # Lowercase English
					"smartid",           # SmartID (might be in the content)
					"SmartID",           # SmartID capitalized
					"App",               # App authentication
					"Tjänstekort",       # Service card
					"Tj&#228;nstekort",  # HTML entity encoded service card
					"SAML"               # SAML authentication
				]
				
				found_indicators = [indicator for indicator in auth_method_indicators if indicator in selection_text]
				_LOGGER.error(f"*** FOUND AUTH INDICATORS v0.0.48 *** {found_indicators}")
				
				# Check for password option with HTML entities and encodings
				password_indicators = ["Lösenord", "Password", "L%C3%B6senord", "L&#246;senord", "L&#37;c3&#37;b6senord", "lösenord", "password"]
				has_password_option = any(indicator in selection_text for indicator in password_indicators)
				_LOGGER.error(f"*** PASSWORD OPTION CHECK v0.0.48 *** {has_password_option}")
				
				if "chooseAuthmech" in str(resp.url):
					if has_password_option:
						_LOGGER.error("*** DETECTED AUTH METHOD SELECTION v0.0.47 ***")
						await self._handle_auth_method_selection(selection_text, str(resp.url))
					else:
						# Fallback: Try to construct password URL from URL parameters
						_LOGGER.error("*** NO PASSWORD IN CONTENT - TRYING URL FALLBACK v0.0.47 ***")
						if "L%C3%B6senord" in str(resp.url):
							await self._handle_auth_method_fallback(str(resp.url))
					# Note: Don't return here, let the flow continue to check for more redirects
				elif 'id="openid_message"' in selection_text:
					_LOGGER.error("*** SCHOOL RETURNED AUTO-SUBMIT FORM v0.0.43 ***")
					form_result = await _auto_submit_openid_form(self.session, selection_text, str(resp.url))
					if form_result.executed:
						_LOGGER.error("*** SCHOOL AUTO-SUBMIT COMPLETED v0.0.43 ***")
					
		except Exception as e:
			_LOGGER.error(f"*** SCHOOL SELECTION FAILED v0.0.43 *** {e}")
			_LOGGER.error(f"*** PROBLEMATIC URL v0.0.43 *** {school_url}")
			
			# If school selection fails, try to continue without it
			# Some accounts might not need explicit school selection
			_LOGGER.error("*** CONTINUING WITHOUT SCHOOL SELECTION v0.0.43 ***")

	async def _handle_auth_method_selection(self, html: str, page_url: str) -> None:
		"""Handle authentication method selection by choosing password login."""
		_LOGGER.error("*** PROCESSING AUTH METHOD SELECTION v0.0.44 ***")
		
		import re as _re
		
		# Look for the password option with multiple possible texts including HTML entities
		password_patterns = [
			r'<a[^>]*href=["\']([^"\']*L[^"\']*c3[^"\']*b6senord[^"\']*)["\'][^>]*>.*?L&#246;senord.*?</a>',  # HTML entity with URL check
			r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>.*?Lösenord.*?</a>',
			r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>.*?Password.*?</a>',
			r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>.*?lösenord.*?</a>',
			r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>.*?password.*?</a>',
			r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>.*?L&#246;senord.*?</a>',  # HTML entity fallback
			r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>.*?L&#37;c3&#37;b6senord.*?</a>',  # Double encoded fallback
		]
		
		password_match = None
		for pattern in password_patterns:
			password_match = _re.search(pattern, html, _re.IGNORECASE | _re.DOTALL)
			if password_match:
				_LOGGER.error(f"*** FOUND PASSWORD LINK PATTERN v0.0.46 *** {pattern}")
				break
		
		if password_match:
			password_url = password_match.group(1)
			
			# CRITICAL: Decode HTML entities in the URL before using it
			# The URL often contains things like &#37;c3&#37;b6 which need to be decoded
			import html
			password_url = html.unescape(password_url)
			_LOGGER.error(f"*** DECODED PASSWORD URL v0.0.79 *** {password_url}")
			
			# Handle relative URLs
			from urllib.parse import urljoin
			if password_url.startswith('/'):
				password_url = urljoin(page_url, password_url)
			elif not password_url.startswith('http'):
				# Relative path without leading slash
				base_url = '/'.join(page_url.split('/')[:-1]) + '/'
				password_url = urljoin(base_url, password_url)
			
			_LOGGER.error(f"*** SELECTING PASSWORD AUTH METHOD v0.0.79 *** {password_url}")
			
			headers = DEFAULT_HEADERS.copy()
			headers.update({
				"Referer": page_url,
			})
			
			try:
				await asyncio.sleep(REQUEST_DELAY)
				async with self.session.get(password_url, headers=headers, allow_redirects=True) as resp:
					_LOGGER.error(f"*** AUTH METHOD SELECTION RESULT v0.0.44 *** {resp.status} -> {resp.url}")
					
					auth_method_text = await resp.text()
					
					# Handle any auto-submit forms that might appear
					if 'id="openid_message"' in auth_method_text:
						_LOGGER.error("*** AUTH METHOD RETURNED AUTO-SUBMIT FORM v0.0.44 ***")
						form_result = await _auto_submit_openid_form(self.session, auth_method_text, str(resp.url))
						if form_result.executed:
							_LOGGER.error("*** AUTH METHOD AUTO-SUBMIT COMPLETED v0.0.44 ***")
					
			except Exception as e:
				_LOGGER.error(f"*** AUTH METHOD SELECTION FAILED v0.0.44 *** {e}")
		else:
			_LOGGER.error("*** NO PASSWORD AUTH METHOD FOUND v0.0.44 ***")
			_LOGGER.error(f"*** AUTH METHOD PAGE SNIPPET v0.0.44 *** {html[:500]}...")

	async def _handle_auth_method_fallback(self, page_url: str) -> None:
		"""Fallback method to handle authentication method selection by constructing URL directly."""
		_LOGGER.error("*** PROCESSING AUTH METHOD FALLBACK v0.0.47 ***")
		
		# Extract the base URL and try to construct the password selection URL
		# Example URL: https://idp01.avesta.se/wa/chooseAuthmech?authmechs=App%20-%20SmartID:App%20-%20SmartID;L%C3%B6senord:L%C3%B6senord;Tj%C3%A4nstekort:Tj%C3%A4nstekort
		
		base_url = page_url.split('?')[0]  # Get base URL without parameters
		
		# Try common password authentication URLs
		possible_password_urls = [
			f"{base_url}?method=password",
			f"{base_url}?auth=password", 
			f"{base_url}?type=password",
			f"{base_url}?authmech=password",
			f"{base_url}?authmech=L%C3%B6senord",  # URL encoded Swedish
			f"{base_url}?authmech=Lösenord",       # Swedish
			# Try with the ID from the URL structure
			f"{base_url.replace('/chooseAuthmech', '/login')}?method=password",
		]
		
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Referer": page_url,
		})
		
		for password_url in possible_password_urls:
			try:
				_LOGGER.error(f"*** TRYING FALLBACK URL v0.0.47 *** {password_url}")
				await asyncio.sleep(REQUEST_DELAY)
				
				async with self.session.get(password_url, headers=headers, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as resp:
					if resp.status == 200:
						_LOGGER.error(f"*** FALLBACK URL SUCCESS v0.0.47 *** {resp.status} -> {resp.url}")
						auth_result_text = await resp.text()
						
						# Check if this led to a login form or another redirect
						if any(field in auth_result_text.lower() for field in ['txtnotandanafn', 'txtlykilord', 'password', 'username']):
							_LOGGER.error("*** FALLBACK LED TO LOGIN FORM v0.0.47 ***")
							return  # Success - let the normal flow handle the login form
						elif 'id="openid_message"' in auth_result_text:
							_LOGGER.error("*** FALLBACK RETURNED AUTO-SUBMIT FORM v0.0.47 ***")
							form_result = await _auto_submit_openid_form(self.session, auth_result_text, str(resp.url))
							if form_result.executed:
								_LOGGER.error("*** FALLBACK AUTO-SUBMIT COMPLETED v0.0.47 ***")
								return
						else:
							_LOGGER.error(f"*** FALLBACK URL UNCLEAR RESULT v0.0.47 *** {auth_result_text[:200]}...")
					else:
						_LOGGER.error(f"*** FALLBACK URL FAILED v0.0.47 *** {resp.status}")
						
			except Exception as e:
				_LOGGER.error(f"*** FALLBACK URL EXCEPTION v0.0.47 *** {password_url} -> {e}")
				continue
		
		_LOGGER.error("*** ALL FALLBACK URLS FAILED v0.0.47 ***")

	async def _direct_login_with_credentials(self, username: str, password: str) -> None:
		"""Login directly using username/password on the main InfoMentor login page."""
		_LOGGER.error("*** STARTING DIRECT LOGIN v0.0.51 ***")
		
		# Go to the main login page
		login_url = "https://infomentor.se/swedish/production/mentor/"
		headers = DEFAULT_HEADERS.copy()
		
		try:
			# First, get the login page to see the form
			await asyncio.sleep(REQUEST_DELAY)
			async with self.session.get(login_url, headers=headers) as resp:
				login_page = await resp.text()
				_LOGGER.error(f"*** LOGIN PAGE RESPONSE v0.0.51 *** {resp.status} -> {resp.url}")
				_LOGGER.error(f"*** LOGIN PAGE LENGTH v0.0.51 *** {len(login_page)} chars")
				
				# Save for debugging
				await _write_text_file_async("/tmp/infomentor_login_page.html", login_page)
				_LOGGER.error("*** SAVED LOGIN PAGE v0.0.51 *** /tmp/infomentor_login_page.html")
				
				# Look for the login form
				import re
				
				# Find the form action URL
				form_pattern = r'<form[^>]*action=["\']([^"\']*)["\'][^>]*>'
				form_match = re.search(form_pattern, login_page, re.IGNORECASE)
				
				if not form_match:
					_LOGGER.error("*** NO LOGIN FORM FOUND v0.0.51 ***")
					raise InfoMentorAuthError("Could not find login form on main page")
				
				form_action = form_match.group(1)
				_LOGGER.error(f"*** FOUND LOGIN FORM v0.0.51 *** action={form_action}")
				
				# Look for username and password field names
				username_patterns = [
					r'<input[^>]*name=["\']([^"\']*)["\'][^>]*(?:type=["\']text["\']|type=["\']email["\'])',
					r'<input[^>]*(?:type=["\']text["\']|type=["\']email["\'])[^>]*name=["\']([^"\']*)["\']'
				]
				
				password_patterns = [
					r'<input[^>]*name=["\']([^"\']*)["\'][^>]*type=["\']password["\']',
					r'<input[^>]*type=["\']password["\'][^>]*name=["\']([^"\']*)["\']'
				]
				
				username_field = None
				password_field = None
				
				for pattern in username_patterns:
					match = re.search(pattern, login_page, re.IGNORECASE)
					if match:
						username_field = match.group(1)
						break
				
				for pattern in password_patterns:
					match = re.search(pattern, login_page, re.IGNORECASE)
					if match:
						password_field = match.group(1)
						break
				
				_LOGGER.error(f"*** LOGIN FIELDS v0.0.51 *** username={username_field}, password={password_field}")
				
				if not username_field or not password_field:
					_LOGGER.error("*** COULD NOT FIND LOGIN FIELDS v0.0.51 ***")
					raise InfoMentorAuthError("Could not find username/password fields")
				
				# Prepare form data
				form_data = {
					username_field: username,
					password_field: password
				}
				
				# Look for any hidden fields (CSRF tokens, etc.)
				hidden_pattern = r'<input[^>]*type=["\']hidden["\'][^>]*name=["\']([^"\']*)["\'][^>]*value=["\']([^"\']*)["\']'
				hidden_matches = re.findall(hidden_pattern, login_page, re.IGNORECASE)
				
				for field_name, field_value in hidden_matches:
					form_data[field_name] = field_value
					_LOGGER.error(f"*** HIDDEN FIELD v0.0.51 *** {field_name}={field_value}")
				
				# Construct the full form action URL
				if form_action.startswith('/'):
					form_url = f"https://infomentor.se{form_action}"
				elif not form_action.startswith('http'):
					form_url = f"https://infomentor.se/swedish/production/mentor/{form_action}"
				else:
					form_url = form_action
				
				_LOGGER.error(f"*** SUBMITTING LOGIN FORM v0.0.51 *** {form_url}")
				_LOGGER.error(f"*** FORM DATA v0.0.51 *** {list(form_data.keys())}")
				
				# Submit the login form
				headers.update({
					"Content-Type": "application/x-www-form-urlencoded",
					"Referer": login_url,
					"Origin": "https://infomentor.se"
				})
				
				await asyncio.sleep(REQUEST_DELAY)
				async with self.session.post(form_url, data=form_data, headers=headers, allow_redirects=True) as resp:
					login_result = await resp.text()
					_LOGGER.error(f"*** LOGIN RESULT v0.0.51 *** {resp.status} -> {resp.url}")
					_LOGGER.error(f"*** LOGIN RESULT LENGTH v0.0.51 *** {len(login_result)} chars")
					
					# Save for debugging
					await _write_text_file_async("/tmp/infomentor_login_result.html", login_result)
					_LOGGER.error("*** SAVED LOGIN RESULT v0.0.51 *** /tmp/infomentor_login_result.html")
					
					# Check if login was successful (look for signs of the main dashboard)
					success_indicators = [
						"student-menu",  # Main menu for students
						"pupil-selection", # Pupil selection
						"dashboard",  # Dashboard elements
						"mentor-main", # Main mentor interface
						"logout",  # Logout link indicates successful login
						"logga ut"  # Swedish logout
					]
					
					is_success = any(indicator in login_result.lower() for indicator in success_indicators)
					
					if is_success:
						_LOGGER.error("*** DIRECT LOGIN SUCCESS v0.0.51 ***")
					else:
						# Check for error messages
						error_indicators = [
							"felaktigt",  # Incorrect (Swedish)
							"error",
							"failed",
							"invalid",
							"wrong"
						]
						
						has_error = any(indicator in login_result.lower() for indicator in error_indicators)
						
						if has_error:
							_LOGGER.error("*** DIRECT LOGIN FAILED - INVALID CREDENTIALS v0.0.51 ***")
							raise InfoMentorAuthError("Invalid username or password")
						else:
							_LOGGER.error("*** DIRECT LOGIN UNCLEAR RESULT v0.0.51 ***")
							_LOGGER.error(f"*** RESULT SAMPLE v0.0.51 *** {login_result[:500]}...")
		
		except Exception as e:
			_LOGGER.error(f"*** DIRECT LOGIN EXCEPTION v0.0.51 *** {e}")
			raise

	async def _verify_authentication_status(self) -> None:
		"""Verify authentication status by attempting to access protected resources."""
		_LOGGER.debug("Verifying authentication status")
		
		test_endpoints = [
			f"{HUB_BASE_URL}/",
			f"{HUB_BASE_URL}/#/",
			f"{MODERN_BASE_URL}/",
			"https://infomentor.se/Swedish/Production/mentor/default.aspx"
		]
		
		for endpoint in test_endpoints:
			try:
				headers = DEFAULT_HEADERS.copy()
				async with self.session.get(endpoint, headers=headers, allow_redirects=True) as resp:
					if resp.status == 200:
						text = await resp.text()
						
						# Check for authenticated content
						authenticated_indicators = [
							"logout" in text.lower(),
							"pupil" in text.lower(),
							"elev" in text.lower(),
							"dashboard" in text.lower(),
							"switchpupil" in text.lower(),
						]
						
						if any(authenticated_indicators):
							_LOGGER.debug(f"Authentication verified successfully via {endpoint}")
							return
			except Exception as e:
				_LOGGER.debug(f"Failed to verify authentication via {endpoint}: {e}")
				continue
		
		# If we get here, authentication verification failed
		_LOGGER.warning("Could not verify authentication status - OAuth may have failed")
		# Don't raise an exception as the integration might still work partially
	
	async def _try_alternative_hub_access(self, headers: dict) -> None:
		"""Try alternative methods to access the hub dashboard."""
		_LOGGER.error("*** TRYING ALTERNATIVE HUB ACCESS v0.0.53 ***")
		
		# List of alternative URLs to try
		alternative_urls = [
			f"{HUB_BASE_URL}/home",
			f"{HUB_BASE_URL}/start", 
			f"{HUB_BASE_URL}/dashboard",
			f"{HUB_BASE_URL}/account",
		]
		
		for alt_url in alternative_urls:
			try:
				_LOGGER.error(f"*** TRYING ALTERNATIVE URL v0.0.53 *** {alt_url}")
				await asyncio.sleep(REQUEST_DELAY)
				async with self.session.get(alt_url, headers=headers, allow_redirects=True) as resp:
					_LOGGER.error(f"*** ALTERNATIVE URL RESPONSE v0.0.53 *** {resp.status} -> {resp.url}")
					
					# If we get a good response without auto-submit, we might have found the right path
					alt_text = await resp.text()
					if len(alt_text) > 10000 and 'id="openid_message"' not in alt_text:
						_LOGGER.error(f"*** FOUND GOOD ALTERNATIVE v0.0.53 *** {alt_url} -> {len(alt_text)} chars")
						await _write_text_file_async(f"/tmp/infomentor_hub_alt_{alt_url.split('/')[-1]}.html", alt_text)
						break
			except Exception as e:
				_LOGGER.error(f"*** ALTERNATIVE URL ERROR v0.0.53 *** {alt_url}: {e}")
				continue
	
	async def _get_pupil_ids_modern(self) -> list[str]:
		"""Get pupil IDs from modern InfoMentor Hub interface."""
		_LOGGER.error("*** GETTING PUPIL IDS FROM HUB v0.0.64 ***")
		
		# Add loop detection to prevent infinite redirect cycles
		school_selection_attempts = 0
		max_school_selection_attempts = 2
		auto_submit_attempts = 0
		max_auto_submit_attempts = 3
		
		try:
			# Try the main hub dashboard root (where OAuth leads us)
			dashboard_url = f"{HUB_BASE_URL}/"
			headers = DEFAULT_HEADERS.copy()
			
			# Try the main hub dashboard root (where OAuth leads us)
			await asyncio.sleep(REQUEST_DELAY)
			async with self.session.get(dashboard_url, headers=headers) as resp:
				_LOGGER.error(f"*** HUB DASHBOARD REQUEST v0.0.64 *** {dashboard_url} -> status: {resp.status}")
				text = await resp.text()
				_LOGGER.error(f"*** HUB DASHBOARD CONTENT LENGTH v0.0.64 *** {len(text)}")
				
				# Save hub dashboard response for analysis
				await _write_text_file_async("/tmp/infomentor_hub_dashboard.html", text)
				_LOGGER.error("*** SAVED HUB DASHBOARD v0.0.53 *** /tmp/infomentor_hub_dashboard.html")
				
				# Handle auto-submit form - try multiple strategies to get real hub content
				if ('id="openid_message"' in text) or ('id=\'openid_message\'' in text):
					auto_submit_attempts += 1
					_LOGGER.error(f"*** DETECTED AUTO-SUBMIT FORM ON HUB v0.0.64 *** attempt {auto_submit_attempts}/{max_auto_submit_attempts}")
					_LOGGER.error(f"*** CONTENT LENGTH IS ONLY {len(text)} - NEED TO GET REAL HUB v0.0.64 ***")
					
					# Prevent infinite auto-submit loops
					if auto_submit_attempts > max_auto_submit_attempts:
						_LOGGER.error(f"*** AUTO-SUBMIT LOOP DETECTED v0.0.64 *** stopping after {auto_submit_attempts} attempts")
						raise InfoMentorAuthError("Auto-submit loop detected - authentication failed")
					
					# Check if the auto-submit would take us to legacy interface
					action_match = re.search(r'action=["\']([^"\']+)["\']', text, re.IGNORECASE)
					if action_match:
						action_url = action_match.group(1)
						_LOGGER.error(f"*** AUTO-SUBMIT ACTION URL v0.0.64 *** {action_url}")
						
						# If it would take us to legacy, try alternative approaches first
						if "infomentor.se/swedish/production/mentor" in action_url.lower():
							_LOGGER.error("*** AUTO-SUBMIT LEADS TO LEGACY - TRYING ALTERNATIVES v0.0.64 ***")
							
							# Strategy 1: Try multiple hub URLs to find one that works
							hub_alternatives = [
								f"{HUB_BASE_URL}/home",
								f"{HUB_BASE_URL}/start", 
								f"{HUB_BASE_URL}/dashboard",
								f"{HUB_BASE_URL}/#/",
							]
							
							found_real_hub = False
							for alt_url in hub_alternatives:
								try:
									_LOGGER.error(f"*** TRYING HUB ALTERNATIVE v0.0.55 *** {alt_url}")
									await asyncio.sleep(REQUEST_DELAY)
									async with self.session.get(alt_url, headers=headers, allow_redirects=True) as alt_resp:
										alt_text = await alt_resp.text()
										_LOGGER.error(f"*** ALTERNATIVE RESULT v0.0.55 *** {alt_resp.status} -> {len(alt_text)} chars")
										
										# If we get substantial content without auto-submit, use it
										if len(alt_text) > 10000 and 'id="openid_message"' not in alt_text:
											_LOGGER.error(f"*** FOUND REAL HUB CONTENT v0.0.55 *** {alt_url}")
											text = alt_text
											found_real_hub = True
											await _write_text_file_async("/tmp/infomentor_hub_alternative_success.html", text)
											break
								except Exception as e:
									_LOGGER.error(f"*** ALTERNATIVE ERROR v0.0.55 *** {alt_url}: {e}")
									continue
							
							# Strategy 2: If alternatives failed, wait and retry main hub URL
							if not found_real_hub:
								_LOGGER.error("*** ALTERNATIVES FAILED - WAITING AND RETRYING MAIN HUB v0.0.55 ***")
								await asyncio.sleep(REQUEST_DELAY * 3)  # Wait longer
								async with self.session.get(dashboard_url, headers=headers) as retry_resp:
									retry_text = await retry_resp.text()
									_LOGGER.error(f"*** RETRY RESULT v0.0.55 *** {retry_resp.status} -> {len(retry_text)} chars")
									
									if len(retry_text) > 10000 and 'id="openid_message"' not in retry_text:
										_LOGGER.error("*** RETRY FOUND REAL HUB CONTENT v0.0.55 ***")
										text = retry_text
										found_real_hub = True
									else:
										_LOGGER.error("*** RETRY STILL RETURNS AUTO-SUBMIT - PROCEEDING WITH FORM v0.0.55 ***")
							
							# Strategy 3: If everything failed, follow the auto-submit as last resort
							if not found_real_hub:
								_LOGGER.error("*** ALL STRATEGIES FAILED - FOLLOWING AUTO-SUBMIT v0.0.55 ***")
								form_result = await _auto_submit_openid_form(self.session, text, referer=dashboard_url)
								if form_result.executed and form_result.final_text:
									text = form_result.final_text
									_LOGGER.error(f"*** USING AUTO-SUBMIT RESULT v0.0.55 *** length={len(text)}")
						else:
							# Safe to follow the auto-submit
							_LOGGER.error("*** AUTO-SUBMIT SAFE - PROCEEDING v0.0.55 ***")
							form_result = await _auto_submit_openid_form(self.session, text, referer=dashboard_url)
							if form_result.executed and form_result.final_text:
								text = form_result.final_text
								_LOGGER.error(f"*** USING AUTO-SUBMIT FINAL RESPONSE v0.0.55 *** length={len(text)}")
					else:
						_LOGGER.error("*** NO ACTION URL FOUND IN AUTO-SUBMIT FORM v0.0.55 ***")

				# Handle school/municipality selection page (with loop protection)
				if "IdpListRepeater" in text and ("elever" in text or "kommun" in text):
					school_selection_attempts += 1
					_LOGGER.error(f"*** DETECTED SCHOOL SELECTION ON HUB v0.0.64 *** attempt {school_selection_attempts}/{max_school_selection_attempts}")
					
					if school_selection_attempts <= max_school_selection_attempts:
						await self._handle_school_selection(text, dashboard_url)
						# Re-fetch dashboard after school selection
						await asyncio.sleep(REQUEST_DELAY)
						async with self.session.get(dashboard_url, headers=headers) as resp_school:
							text = await resp_school.text()
							_LOGGER.error(f"*** HUB RE-FETCH AFTER SCHOOL SELECTION v0.0.64 *** status={resp_school.status}")
					else:
						_LOGGER.error(f"*** SCHOOL SELECTION LOOP DETECTED v0.0.64 *** stopping after {school_selection_attempts} attempts")
						raise InfoMentorAuthError("School selection loop detected - authentication failed")
				else:
					_LOGGER.error("*** NO SCHOOL SELECTION ON HUB v0.0.64 ***")

				# Detect login error page and attempt re-authentication via login link
				if ("Hoppsan" in text or "Loginsida" in text) and "Authentication/Authentication/Login" in text:
					_LOGGER.warning("Detected login error page on dashboard; attempting to restart login flow")
					# Try to follow the login link if present
					try:
						import re as _re
						login_link_match = _re.search(r'href=\"(https://hub\.infomentor\.se[^\"]*Authentication/Authentication/Login[^\"]*)\"', text, _re.IGNORECASE)
						if login_link_match:
							login_url = login_link_match.group(1)
							await asyncio.sleep(REQUEST_DELAY)
							async with self.session.get(login_url, headers=headers, allow_redirects=True) as login_resp:
								_LOGGER.debug(f"Followed login link, status={login_resp.status}")
					except Exception as e_login:
						_LOGGER.debug(f"Following login link failed: {e_login}")
					# Attempt full re-authentication if we have stored creds
					try:
						await self.reauthenticate()
						# Re-fetch dashboard
						await asyncio.sleep(REQUEST_DELAY)
						async with self.session.get(dashboard_url, headers=headers) as resp3:
							text = await resp3.text()
							_LOGGER.debug(f"Dashboard fetch after reauthentication: status={resp3.status}")
					except Exception as e_reauth:
						_LOGGER.debug(f"Reauthentication attempt failed: {e_reauth}")

				# Check if we're on the legacy interface (auto-submit result)
				if "infomentor.se/swedish/production/mentor/" in str(resp.url) or "mentor/" in text:
					_LOGGER.error("*** DETECTED LEGACY INTERFACE - USING LEGACY EXTRACTION v0.0.70 ***")
					pupil_ids = await self._extract_pupil_ids_legacy(text)
				else:
					_LOGGER.error("*** USING HUB JSON EXTRACTION v0.0.70 ***")
					pupil_ids = self._extract_pupil_ids_from_json(text)

				if pupil_ids:
					_LOGGER.debug(f"Found {len(pupil_ids)} pupil IDs from dashboard")
					return pupil_ids
				
				# If no pupil IDs found, try alternative URLs
				alternative_urls = [
					f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true",
					f"{HUB_BASE_URL}/dashboard",
					f"{HUB_BASE_URL}/",
					f"{MODERN_BASE_URL}/start",
					f"{MODERN_BASE_URL}/dashboard"
				]
				
				for alt_url in alternative_urls:
					_LOGGER.debug(f"Trying alternative URL: {alt_url}")
					try:
						await asyncio.sleep(REQUEST_DELAY)
						async with self.session.get(alt_url, headers=headers) as alt_resp:
							_LOGGER.debug(f"Alternative URL {alt_url} returned status: {alt_resp.status}")
						alt_text = await alt_resp.text()
						# Handle auto-submit forms on alternative URLs as well
						if ('id="openid_message"' in alt_text) or ('id=\'openid_message\'' in alt_text):
							_LOGGER.debug(f"Detected OpenID form on {alt_url}; submitting...")
							form_result = await _auto_submit_openid_form(self.session, alt_text, referer=alt_url)
							if form_result.executed:
								# Re-fetch the same alt URL
								await asyncio.sleep(REQUEST_DELAY)
								async with self.session.get(alt_url, headers=headers) as alt_resp2:
									alt_text = await alt_resp2.text()
							# Detect login error pages on alt URLs too
							if ("Hoppsan" in alt_text or "Loginsida" in alt_text) and "Authentication/Authentication/Login" in alt_text:
								_LOGGER.warning(f"Detected login error page on {alt_url}; attempting re-authentication")
								try:
									await self.reauthenticate()
									await asyncio.sleep(REQUEST_DELAY)
									async with self.session.get(alt_url, headers=headers) as alt_resp3:
										alt_text = await alt_resp3.text()
								except Exception as e_reauth2:
									_LOGGER.debug(f"Reauthentication via alt URL failed: {e_reauth2}")
							# Check if we're on the legacy interface from alternative URL
							if "infomentor.se/swedish/production/mentor/" in str(alt_resp.url) or "mentor/" in alt_text:
								_LOGGER.error("*** DETECTED LEGACY INTERFACE FROM ALT URL - USING LEGACY EXTRACTION v0.0.70 ***")
								pupil_ids = await self._extract_pupil_ids_legacy(alt_text)
							else:
								_LOGGER.error("*** USING HUB JSON EXTRACTION FROM ALT URL v0.0.70 ***")
								pupil_ids = self._extract_pupil_ids_from_json(alt_text)

							if pupil_ids:
								_LOGGER.debug(f"Found {len(pupil_ids)} pupil IDs from {alt_url}")
								return pupil_ids
					except Exception as e:
						_LOGGER.debug(f"Failed to fetch {alt_url}: {e}")
						continue
				
				# Save debug artefacts and log a snippet if no pupil IDs found
				try:
					_LOGGER.error(f"No pupil IDs found on dashboard. Server response (truncated): {text[:500]}...")
				except Exception:
					pass
				await _write_text_file_async(DEBUG_FILE_DASHBOARD, text)
				_LOGGER.debug(f"Saved dashboard debug HTML to {DEBUG_FILE_DASHBOARD}")
				# If we still cannot find pupils, raise a specific error for coordinator to handle
				raise InfoMentorAuthError("Dashboard did not contain pupil data")
				
				return []
				
		except Exception as e:
			_LOGGER.error(f"Error getting pupil IDs from modern interface: {e}")
			
			# Fallback to legacy method
			_LOGGER.debug("Falling back to legacy pupil ID extraction")
			try:
				return await self._get_pupil_ids_legacy()
			except Exception as legacy_e:
				_LOGGER.error(f"Legacy pupil ID extraction also failed: {legacy_e}")
				return []
	
	def _extract_pupil_ids_from_json(self, html_content: str) -> list[str]:
		"""Extract pupil IDs from JSON data embedded in HTML."""
		pupil_ids = []
		
		try:
			# Try multiple JSON extraction patterns
			json_patterns = [
				# InfoMentor Hub specific patterns (for modern hub interface)
				r'IMHome\.home\.homeData\s*=\s*(\{.*?\});',  # The homeData object with pupil info
				r'"pupils"\s*:\s*(\[.*?\])',               # The pupils array specifically
				r'IMHome\s*=\s*(\{.*?\});',               # The main IMHome JavaScript object
				r'init\s*:\s*(\{.*?\}),',                 # The init object within IMHome
				
				# Standard JSON assignment patterns
				r'var\s+pupils\s*=\s*(\[.*?\]);',
				r'pupils\s*:\s*(\[.*?\])',
				r'children\s*:\s*(\[.*?\])',
				r'"children"\s*:\s*(\[.*?\])',
				r'students\s*:\s*(\[.*?\])',
				r'"students"\s*:\s*(\[.*?\])',
				
				# Angular/Vue.js data patterns
				r'ng-init[^>]*pupils\s*=\s*(\[.*?\])',
				r'v-data[^>]*pupils\s*=\s*(\[.*?\])',
				r'data-pupils=["\'](\[.*?\])["\']',
				
				# Look specifically for pupil switcher data
				r'"switchPupilUrl"[^}]*"hybridMappingId"[^}]*(\{[^}]*\})',
			]
			
			for pattern in json_patterns:
				matches = re.findall(pattern, html_content, re.DOTALL | re.IGNORECASE)
				for match in matches:
					try:
						# Try to parse as JSON
						if match.startswith('[') or match.startswith('{'):
							data = json.loads(match)
							ids = self._extract_ids_from_data(data)
							pupil_ids.extend(ids)
							_LOGGER.debug(f"Extracted {len(ids)} pupil IDs from JSON pattern: {pattern}")
					except json.JSONDecodeError as e:
						_LOGGER.debug(f"JSON decode error for pattern {pattern}: {e}")
						continue
			
			# Try InfoMentor Hub specific patterns first - but prioritize pupils array
			_LOGGER.error(f"*** TRYING HUB-SPECIFIC EXTRACTION v0.0.53 *** found {len(pupil_ids)} from JSON")
			
			# Look for the comprehensive pupils array in IMHome.home.homeData - PRIORITY extraction
			homedata_pattern = r'IMHome\.home\.homeData\s*=\s*(\{.*?"pupils"\s*:\s*\[.*?\].*?\});'
			homedata_matches = re.findall(homedata_pattern, html_content, re.DOTALL | re.IGNORECASE)
			
			hub_specific_pupil_ids = []  # Use separate list for hub-specific extraction
			hub_specific_pupil_names = {}  # Store names too
			
			for homedata_json in homedata_matches:
				_LOGGER.error(f"*** FOUND HOMEDATA JSON v0.0.54 *** length={len(homedata_json)}")
				try:
					homedata = json.loads(homedata_json)
					if 'account' in homedata and 'pupils' in homedata['account']:
						pupils_data = homedata['account']['pupils']
						_LOGGER.error(f"*** FOUND PUPILS ARRAY v0.0.54 *** count={len(pupils_data)}")
						
						for pupil in pupils_data:
							pupil_id = str(pupil.get('id', ''))
							pupil_name = pupil.get('name', '')
							_LOGGER.error(f"*** PROCESSING PUPIL v0.0.54 *** id={pupil_id} name={pupil_name}")
							if pupil_id and pupil_id not in hub_specific_pupil_ids:
								hub_specific_pupil_ids.append(pupil_id)
								hub_specific_pupil_names[pupil_id] = pupil_name
								_LOGGER.error(f"*** EXTRACTED PUPIL v0.0.54 *** id={pupil_id} name={pupil_name}")
								
						# If we found pupils via hub-specific method, prioritize them
						if hub_specific_pupil_ids:
							_LOGGER.error(f"*** USING HUB-SPECIFIC PUPILS v0.0.54 *** count={len(hub_specific_pupil_ids)}")
							pupil_ids = hub_specific_pupil_ids  # Replace any previously found IDs
							
							# Store the pupil names for later use
							self.pupil_names = hub_specific_pupil_names
							_LOGGER.error(f"*** STORED PUPIL NAMES v0.0.54 *** {self.pupil_names}")
							
							# Skip filtering for hub-specific pupils since they're from authoritative source
							_LOGGER.error(f"*** RETURNING HUB-SPECIFIC PUPILS WITHOUT FILTERING v0.0.54 *** {pupil_ids}")
							return list(set(pupil_ids))  # Remove duplicates and return immediately
							
				except (json.JSONDecodeError, KeyError) as e:
					_LOGGER.error(f"*** HOMEDATA PARSING ERROR v0.0.53 *** {e}")
			
			# Fallback: Look for selectedPupilName pattern (single selected pupil)
			if not pupil_ids:
				selected_pupil_pattern = r'selectedPupilName\s*:\s*["\']([^"\']+)["\']'
				selected_matches = re.findall(selected_pupil_pattern, html_content, re.IGNORECASE)
				for pupil_name in selected_matches:
					_LOGGER.error(f"*** FOUND SELECTED PUPIL NAME v0.0.53 *** {pupil_name}")
					
				# Look for pupil data in the IMHome.init object specifically
				imhome_pattern = r'IMHome\s*=\s*\{[^}]*init\s*:\s*\{([^}]*selectedPupilName[^}]*)\}'
				imhome_matches = re.findall(imhome_pattern, html_content, re.DOTALL | re.IGNORECASE)
				for init_content in imhome_matches:
					_LOGGER.error(f"*** FOUND IMHOME INIT CONTENT v0.0.53 *** {init_content[:200]}...")
					# Look for any numeric IDs in this context
					id_pattern = r'(\d{6,12})'  # Extended range for longer IDs
					potential_ids = re.findall(id_pattern, init_content)
					for potential_id in potential_ids:
						if potential_id not in pupil_ids and len(potential_id) >= 6:
							pupil_ids.append(potential_id)
							_LOGGER.error(f"*** EXTRACTED PUPIL ID FROM IMHOME v0.0.53 *** {potential_id}")
			
			# If JSON extraction didn't find enough, try more specific regex patterns
			if len(pupil_ids) < 1:  # At least expect one pupil
				_LOGGER.debug("JSON extraction found few results, trying specific regex patterns")
				
				# Look for pupil switcher URLs specifically - these are more reliable
				switcher_pattern = r'"switchPupilUrl"\s*:\s*"[^"]*SwitchPupil/(\d{4,8})"[^}]*"name"\s*:\s*"([^"]+)"'
				switcher_matches = re.findall(switcher_pattern, html_content, re.IGNORECASE | re.DOTALL)
				
				for pupil_id, name in switcher_matches:
					# Filter out entries that look like parent/user accounts
					if self._is_likely_pupil_name(name) and pupil_id not in pupil_ids:
						pupil_ids.append(pupil_id)
						_LOGGER.debug(f"Found pupil {pupil_id} with name '{name}' from switcher pattern")
				
				# If still not enough, try hybridMappingId pattern (more specific)
				if len(pupil_ids) < 2:
					hybrid_pattern = r'"hybridMappingId"\s*:\s*"[^|]*\|(\d{4,8})\|[^"]*"[^}]*"name"\s*:\s*"([^"]+)"'
					hybrid_matches = re.findall(hybrid_pattern, html_content, re.IGNORECASE | re.DOTALL)
					
					for pupil_id, name in hybrid_matches:
						if self._is_likely_pupil_name(name) and pupil_id not in pupil_ids:
							pupil_ids.append(pupil_id)
							_LOGGER.debug(f"Found pupil {pupil_id} with name '{name}' from hybrid pattern")
			
			# Remove duplicates and validate final list
			unique_pupil_ids = list(set(pupil_ids))
			_LOGGER.error(f"*** UNIQUE PUPIL IDS v0.0.53 *** {unique_pupil_ids}")
			
			# Filter out any IDs that seem to be parent/user accounts
			filtered_pupil_ids = []
			for pupil_id in unique_pupil_ids:
				is_likely_pupil = self._is_likely_pupil_id(pupil_id, html_content)
				_LOGGER.error(f"*** FILTERING PUPIL ID v0.0.53 *** {pupil_id} -> likely_pupil={is_likely_pupil}")
				if is_likely_pupil:
					filtered_pupil_ids.append(pupil_id)
					_LOGGER.error(f"*** KEPT PUPIL ID v0.0.53 *** {pupil_id}")
				else:
					_LOGGER.error(f"*** FILTERED OUT PUPIL ID v0.0.53 *** {pupil_id}")
			
			_LOGGER.error(f"*** FINAL FILTERED PUPIL IDS v0.0.53 *** {len(filtered_pupil_ids)} pupils: {filtered_pupil_ids}")
			
			return filtered_pupil_ids
			
		except Exception as e:
			_LOGGER.error(f"Error extracting pupil IDs: {e}")
			return []
	
	def _is_likely_pupil_name(self, name: str) -> bool:
		"""Check if a name is likely to belong to a pupil (not a parent/user)."""
		if not name or len(name.strip()) < 2:
			return False
		
		name_lower = name.lower().strip()
		
		# Filter out obvious non-pupil entries
		parent_indicators = [
			'parent', 'förälder', 'guardian', 'vårdnadshavare',
			'user', 'användare', 'account', 'konto',
			'admin', 'administrator', 'staff', 'personal',
			'@', 'email', 'mail'  # Email addresses
		]
		
		for indicator in parent_indicators:
			if indicator in name_lower:
				return False
		
		# Names that are just numbers are suspicious
		if name.strip().isdigit():
			return False
		
		# Very long names are often system accounts
		if len(name) > 50:
			return False
		
		return True
	
	def _is_likely_pupil_id(self, pupil_id: str, html_content: str) -> bool:
		"""Check if an ID is likely to belong to a pupil."""
		# Look for context around this ID in the HTML
		# If it's associated with pupil-specific functions, it's likely a pupil
		
		pupil_contexts = [
			f'SwitchPupil/{pupil_id}',
			f'"pupilId".*{pupil_id}',
			f'"elevId".*{pupil_id}',
			f'"studentId".*{pupil_id}',
		]
		
		parent_contexts = [
			f'"userId".*{pupil_id}',
			f'"parentId".*{pupil_id}',
			f'"guardianId".*{pupil_id}',
			f'parent.*{pupil_id}',
			f'guardian.*{pupil_id}',
		]
		
		# Check if this ID appears in pupil contexts
		pupil_context_found = False
		for pattern in pupil_contexts:
			if re.search(pattern, html_content, re.IGNORECASE):
				pupil_context_found = True
				break
		
		# Check if this ID appears in parent contexts
		parent_context_found = False
		for pattern in parent_contexts:
			if re.search(pattern, html_content, re.IGNORECASE):
				parent_context_found = True
				break
		
		# If found in parent context but not pupil context, likely not a pupil
		if parent_context_found and not pupil_context_found:
			return False
		
		# If found in pupil context, likely a pupil
		if pupil_context_found:
			return True
		
		# Default to including if no clear indicators either way
		return True
	
	def _extract_ids_from_data(self, data) -> list[str]:
		"""Extract pupil IDs from parsed JSON data."""
		ids = []
		
		if isinstance(data, list):
			for item in data:
				ids.extend(self._extract_ids_from_data(item))
		elif isinstance(data, dict):
			# Look for common ID field names
			id_fields = ['id', 'pupilId', 'elevId', 'studentId', 'userId', 'personId']
			for field in id_fields:
				if field in data:
					value = str(data[field])
					if value.isdigit() and 4 <= len(value) <= 12:  # Extended to support 10-digit IDs
						ids.append(value)
			
			# Recursively check nested objects
			for value in data.values():
				if isinstance(value, (list, dict)):
					ids.extend(self._extract_ids_from_data(value))
		
		return ids
	
	async def _extract_pupil_ids_legacy(self, html_content: str) -> list[str]:
		"""Extract pupil IDs from legacy InfoMentor interface."""
		_LOGGER.error("*** EXTRACTING PUPIL IDS FROM LEGACY INTERFACE v0.0.70 ***")

		try:
			# We already have the HTML content from the auto-submit result
			text = html_content

			# Save for debugging
			await _write_text_file_async("/tmp/infomentor_legacy_dashboard.html", text)
			_LOGGER.error("*** SAVED LEGACY DASHBOARD FOR DEBUG v0.0.70 ***")

			# Look for legacy pupil patterns - more comprehensive patterns
			patterns = [
				# Common pupil ID patterns in legacy interface
				r'pupil[^0-9]*(\d+)',
				r'elevid[^0-9]*(\d+)',
				r'id["\']?\s*:\s*["\']?(\d+)["\']?',
				r'value=["\']?(\d{8,12})["\']?',  # 8-12 digit IDs
				r'data-pupil-id=["\']?(\d+)["\']?',
				r'pupil-id["\']?\s*:\s*["\']?(\d+)["\']?',
				# Look for JavaScript arrays/objects with pupil data
				r'var\s+pupils\s*=\s*(\[.*?\]);',
				r'pupils\s*:\s*(\[.*?\])',
				r'children\s*:\s*(\[.*?\])',
				r'"children"\s*:\s*(\[.*?\])',
				r'students\s*:\s*(\[.*?\])',
				r'"students"\s*:\s*(\[.*?\])',
			]

			pupil_ids = []
			for pattern in patterns:
				matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
				_LOGGER.debug(f"Pattern '{pattern}' found matches: {matches}")

				if isinstance(matches, list) and matches:
					if isinstance(matches[0], str) and matches[0].startswith('['):
						# This is a JSON array, try to extract IDs from it
						try:
							# Look for numeric IDs within the JSON
							json_matches = re.findall(r'["\']?(\d{8,12})["\']?', matches[0])
							for match in json_matches:
								if 8 <= len(match) <= 12:  # Reasonable pupil ID length
									pupil_ids.append(match)
						except:
							pass
					else:
						# Regular matches
						for match in matches:
							if isinstance(match, str) and 8 <= len(match) <= 12:
								pupil_ids.append(match)
							elif isinstance(match, tuple):
								for submatch in match:
									if isinstance(submatch, str) and 8 <= len(submatch) <= 12:
										pupil_ids.append(submatch)

			# Remove duplicates and filter for reasonable lengths
			pupil_ids = list(set(pupil_ids))
			pupil_ids = [pid for pid in pupil_ids if 8 <= len(pid) <= 12]

			_LOGGER.error(f"*** FOUND LEGACY PUPIL IDS v0.0.70 *** {pupil_ids}")

			if pupil_ids:
				_LOGGER.debug(f"Found {len(pupil_ids)} legacy pupil IDs: {pupil_ids}")
				return pupil_ids

		except Exception as e:
			_LOGGER.error(f"Legacy pupil ID extraction failed: {e}")

		# If no pupil IDs found, try the old method as fallback
		_LOGGER.error("*** TRYING OLD LEGACY METHOD AS FALLBACK v0.0.70 ***")
		return await self._get_pupil_ids_legacy()

	async def _get_pupil_ids_legacy(self) -> list[str]:
		"""Old legacy extraction method as fallback."""
		try:
			# Try the legacy default page
			legacy_url = "https://infomentor.se/swedish/production/mentor/default.aspx"
			await asyncio.sleep(REQUEST_DELAY)
			async with self.session.get(legacy_url, headers=DEFAULT_HEADERS) as resp:
				if resp.status == 200:
					text = await resp.text()

					# Look for legacy pupil patterns
					patterns = [
						r'pupil[^0-9]*(\d+)',
						r'elevid[^0-9]*(\d+)',
						r'id["\']?\s*:\s*["\']?(\d+)["\']?',
					]

					pupil_ids = []
					for pattern in patterns:
						matches = re.findall(pattern, text, re.IGNORECASE)
						valid_matches = [m for m in matches if 4 <= len(m) <= 12]
						pupil_ids.extend(valid_matches)

					pupil_ids = list(set(pupil_ids))

					if pupil_ids:
						_LOGGER.debug(f"Found legacy fallback pupil IDs: {pupil_ids}")
						return pupil_ids

		except Exception as e:
			_LOGGER.debug(f"Legacy fallback pupil ID extraction failed: {e}")

		return []
	
	async def _build_switch_id_mapping(self) -> None:
		"""Build mapping between pupil IDs and their switch IDs."""
		_LOGGER.debug("Building pupil ID to switch ID mapping")
		
		try:
			# Get the hub page HTML to extract switch URLs
			headers = DEFAULT_HEADERS.copy()
			hub_url = f"{HUB_BASE_URL}/#/"
			
			async with self.session.get(hub_url, headers=headers) as resp:
				if resp.status == 200:
					html = await resp.text()
					
					# Extract switch URLs and pupil names
					switch_pattern = r'"switchPupilUrl"\s*:\s*"[^"]*SwitchPupil/(\d+)"[^}]*"name"\s*:\s*"([^"]+)"'
					matches = re.findall(switch_pattern, html, re.IGNORECASE)
					
					_LOGGER.debug(f"Found {len(matches)} switch URL patterns")
					
					for switch_id, name in matches:
						# Look for the JSON object containing this switch URL
						json_pattern = rf'{{"[^}}]*"switchPupilUrl"[^}}]*SwitchPupil/{re.escape(switch_id)}[^}}]*}}'
						json_match = re.search(json_pattern, html, re.IGNORECASE | re.DOTALL)
						
						if json_match:
							json_object = json_match.group(0)
							
							# Extract hybridMappingId from this object
							hybrid_pattern = r'"hybridMappingId"\s*:\s*"[^|]*\|(\d+)\|'
							hybrid_match = re.search(hybrid_pattern, json_object)
							
							if hybrid_match:
								pupil_id = hybrid_match.group(1)
								
								# Only map if this pupil ID was found in our pupil list
								if pupil_id in self.pupil_ids:
									self.pupil_switch_ids[pupil_id] = switch_id
									_LOGGER.debug(f"Mapped pupil {pupil_id} ({name}) to switch ID {switch_id}")
								else:
									_LOGGER.debug(f"Found pupil {pupil_id} ({name}) but not in our pupil list")
					
					_LOGGER.info(f"Built switch ID mapping for {len(self.pupil_switch_ids)} pupils")
					
		except Exception as e:
			_LOGGER.warning(f"Failed to build switch ID mapping: {e}")
			# Don't fail authentication if switch mapping fails
	
	async def switch_pupil(self, pupil_id: str) -> bool:
		"""Switch to a specific pupil context.
		
		Args:
			pupil_id: ID of pupil to switch to
			
		Returns:
			True if switch successful
		"""
		if pupil_id not in self.pupil_ids:
			raise InfoMentorAuthError(f"Invalid pupil ID: {pupil_id}")
		
		# Use the correct switch ID, not the pupil ID
		switch_id = self.pupil_switch_ids.get(pupil_id, pupil_id)  # fallback to pupil_id if no mapping
		_LOGGER.debug(f"Switching to pupil {pupil_id} using switch ID {switch_id}")
		
		# Create timeout configuration to prevent hanging requests
		timeout = aiohttp.ClientTimeout(total=30.0, connect=10.0)
		
		# Try hub switch first (this is the main endpoint)
		hub_switch_url = f"{HUB_BASE_URL}/Account/PupilSwitcher/SwitchPupil/{switch_id}"
		
		headers = DEFAULT_HEADERS.copy()
		headers["Referer"] = f"{HUB_BASE_URL}/#/"
		
		try:
			# Allow redirects and check for successful switch (200 or 302)
			async with self.session.get(hub_switch_url, headers=headers, allow_redirects=True, timeout=timeout) as resp:
				# 302 Found is the expected response for successful pupil switch
				# 200 OK is also acceptable if the redirect was followed
				success = resp.status in [200, 302]
				if success:
					_LOGGER.debug(f"Successfully switched to pupil {pupil_id} via hub endpoint (status: {resp.status})")
					# Add a longer delay to ensure the switch takes effect on server side
					await asyncio.sleep(2.0)
					return True
				else:
					if resp.status == 400:
						response_text = await resp.text()
						_LOGGER.warning(f"Hub switch HTTP 400 for pupil {pupil_id} (switch ID {switch_id}): {response_text[:100]}...")
						_LOGGER.warning("HTTP 400 may indicate session expiry or invalid switch ID")
					else:
						_LOGGER.warning(f"Hub switch failed for pupil {pupil_id} (switch ID {switch_id}): {resp.status}")
		except asyncio.TimeoutError:
			_LOGGER.warning(f"Hub switch timed out for pupil {pupil_id} (switch ID {switch_id}) after 30 seconds")
		except asyncio.CancelledError:
			_LOGGER.warning(f"Hub switch was cancelled for pupil {pupil_id} (switch ID {switch_id})")
			# Don't re-raise cancellation immediately, try the fallback first
		except Exception as e:
			_LOGGER.warning(f"Hub switch failed for pupil {pupil_id} (switch ID {switch_id}) with exception: {e}")
		
		# Fallback to modern switch
		modern_switch_url = f"{MODERN_BASE_URL}/Account/PupilSwitcher/SwitchPupil/{switch_id}"
		
		headers["Referer"] = f"{MODERN_BASE_URL}/"
		
		try:
			async with self.session.get(modern_switch_url, headers=headers, allow_redirects=True, timeout=timeout) as resp:
				success = resp.status in [200, 302]
				if success:
					_LOGGER.debug(f"Successfully switched to pupil {pupil_id} via modern endpoint (status: {resp.status})")
					# Add a longer delay to ensure the switch takes effect
					await asyncio.sleep(2.0)
					return True
				else:
					_LOGGER.warning(f"Modern switch failed for pupil {pupil_id} (switch ID {switch_id}): {resp.status}")
		except asyncio.TimeoutError:
			_LOGGER.warning(f"Modern switch timed out for pupil {pupil_id} (switch ID {switch_id}) after 30 seconds")
		except asyncio.CancelledError:
			_LOGGER.warning(f"Modern switch was cancelled for pupil {pupil_id} (switch ID {switch_id})")
			# Re-raise cancellation after trying both endpoints
			raise
		except Exception as e:
			_LOGGER.warning(f"Modern switch failed for pupil {pupil_id} (switch ID {switch_id}) with exception: {e}")
		
		_LOGGER.error(f"All switch attempts failed for pupil {pupil_id} (switch ID {switch_id})")
		return False
	
	async def diagnose_auth_state(self) -> dict:
		"""Diagnose current authentication state for troubleshooting.
		
		Returns:
			Dictionary with diagnostic information
		"""
		_LOGGER.debug("Running authentication diagnostics")
		
		diagnostics = {
			"authenticated": self.authenticated,
			"pupil_ids_found": len(self.pupil_ids),
			"pupil_ids": self.pupil_ids,
			"endpoints_accessible": {},
			"session_cookies": len(self.session.cookie_jar),
			"errors": []
		}
		
		# Test access to various endpoints
		test_endpoints = {
			"hub_root": f"{HUB_BASE_URL}/",
			"hub_hash": f"{HUB_BASE_URL}/#/",
			"modern_root": f"{MODERN_BASE_URL}/",
			"legacy_default": "https://infomentor.se/Swedish/Production/mentor/default.aspx"
		}
		
		for name, url in test_endpoints.items():
			try:
				headers = DEFAULT_HEADERS.copy()
				async with self.session.get(url, headers=headers, timeout=10) as resp:
					diagnostics["endpoints_accessible"][name] = {
						"status": resp.status,
						"url": str(resp.url),
						"accessible": resp.status == 200,
						"has_auth_content": False
					}
					
					if resp.status == 200:
						text = await resp.text()
						auth_indicators = [
							"logout" in text.lower(),
							"pupil" in text.lower(),
							"elev" in text.lower(),
							"dashboard" in text.lower(),
							"switchpupil" in text.lower()
						]
						diagnostics["endpoints_accessible"][name]["has_auth_content"] = any(auth_indicators)
			except Exception as e:
				diagnostics["endpoints_accessible"][name] = {
					"status": "error",
					"error": str(e),
					"accessible": False,
					"has_auth_content": False
				}
				diagnostics["errors"].append(f"Failed to access {name}: {e}")
		
		# Log diagnostic summary
		_LOGGER.info(f"Authentication Diagnostics:")
		_LOGGER.info(f"  - Authenticated: {diagnostics['authenticated']}")
		_LOGGER.info(f"  - Pupil IDs found: {diagnostics['pupil_ids_found']}")
		_LOGGER.info(f"  - Session cookies: {diagnostics['session_cookies']}")
		
		accessible_endpoints = [name for name, info in diagnostics["endpoints_accessible"].items() if info.get("accessible")]
		_LOGGER.info(f"  - Accessible endpoints: {accessible_endpoints}")
		
		auth_endpoints = [name for name, info in diagnostics["endpoints_accessible"].items() if info.get("has_auth_content")]
		_LOGGER.info(f"  - Endpoints with auth content: {auth_endpoints}")
		
		if diagnostics["errors"]:
			_LOGGER.warning(f"  - Errors encountered: {len(diagnostics['errors'])}")
		
		return diagnostics 