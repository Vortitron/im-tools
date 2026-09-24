"""Authentication handler for InfoMentor."""

import logging
import re
import json
import asyncio
import html
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
import aiohttp
from urllib.parse import urljoin as _urljoin, urlparse, parse_qs, urlencode
from yarl import URL

from .exceptions import InfoMentorAuthError, InfoMentorConnectionError
from .form_utils import ParsedForm, build_login_form_data, extract_hidden_fields, parse_forms, select_login_form

_LOGGER = logging.getLogger(__name__)

HUB_BASE_URL = "https://hub.infomentor.se"
MODERN_BASE_URL = "https://im.infomentor.se"
LEGACY_BASE_URL = "https://infomentor.se/swedish/production/mentor/"

OAUTH_LOGIN_URL = f"{HUB_BASE_URL}/Authentication/Authentication/Login?apiType=IM1&forceOAuth=true"
OAUTH_LOGIN_URL_WITH_INSTANCE = f"{OAUTH_LOGIN_URL}&apiInstance="

EVENTTARGET_FIELD = "__EVENTTARGET"
EVENTARGUMENT_FIELD = "__EVENTARGUMENT"
VIEWSTATE_FIELD = "__VIEWSTATE"
EVENTVALIDATION_FIELD = "__EVENTVALIDATION"
IDP_REPEATER_TOKEN = "IdpListRepeater"

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
	Pages contain pupil names and session details, so they are only written
	when debug logging is enabled for this integration.
	"""
	if not _LOGGER.isEnabledFor(logging.DEBUG):
		return

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


@dataclass
class SchoolOption:
	title: str
	url: str
	number: Optional[str] = None


def _has_openid_form(page_html: str) -> bool:
	"""Check whether the HTML contains an OpenID/WS-Fed auto-submit form."""
	return 'id="openid_message"' in page_html or "id='openid_message'" in page_html


def _extract_openid_form_action(page_html: str, fallback_url: str) -> str:
	"""Extract the action URL from an openid_message form, handling any attribute order."""
	patterns = [
		r'<form\b[^>]*\bid=["\']openid_message["\'][^>]*\baction=["\']([^"\']+)["\']',
		r'<form\b[^>]*\baction=["\']([^"\']+)["\'][^>]*\bid=["\']openid_message["\']',
	]
	for pattern in patterns:
		match = re.search(pattern, page_html, re.IGNORECASE)
		if match:
			return html.unescape(match.group(1))
	return fallback_url


async def _auto_submit_openid_form(session: aiohttp.ClientSession, page_html: str, referer: str) -> _FormSubmissionResult:
	"""Detect and auto-submit OpenID/WS-Fed forms present in HTML.

	Uses the robust extract_hidden_fields helper so attribute ordering inside
	<input> tags does not matter.  Follows up to 5 chained auto-submit forms
	(hub ↔ legacy ↔ hub round-trips).

	Returns _FormSubmissionResult with executed flag and last response data.
	"""
	try:
		if not _has_openid_form(page_html):
			return _FormSubmissionResult(False)

		current_html = page_html
		current_url = referer

		for hop in range(5):
			if not _has_openid_form(current_html):
				break

			action_url = _extract_openid_form_action(current_html, LEGACY_BASE_URL)
			if action_url and not action_url.startswith("http"):
				action_url = _urljoin(current_url, action_url)

			fields = extract_hidden_fields(current_html)
			inputs = {name: value for name, value in fields}

			if not inputs:
				_LOGGER.warning("OpenID form detected but contained no hidden fields")
				break

			parsed_action = urlparse(action_url)
			origin = f"{parsed_action.scheme}://{parsed_action.netloc}" if parsed_action.scheme else None
			parsed_current = urlparse(current_url)
			same_origin = parsed_action.netloc == parsed_current.netloc

			headers = DEFAULT_HEADERS.copy()
			headers.update({
				"Content-Type": "application/x-www-form-urlencoded",
				"Referer": current_url,
				"Sec-Fetch-Site": "same-origin" if same_origin else "cross-site",
				"Sec-Fetch-Dest": "document",
			})
			if origin:
				headers["Origin"] = origin

			await asyncio.sleep(REQUEST_DELAY)
			async with session.post(action_url, headers=headers, data=urlencode(fields), allow_redirects=True) as resp:
				current_html = await resp.text()
				current_url = str(resp.url)
				_LOGGER.debug(
					"OpenID auto-submit hop %d -> %s ; status=%s final_url=%s (%d chars)",
					hop + 1, action_url, resp.status, resp.url, len(current_html),
				)

		return _FormSubmissionResult(True, current_url, current_html)
	except Exception as e:
		_LOGGER.warning("Auto-submit OpenID form handling failed: %s", e)
		return _FormSubmissionResult(False)


def _choose_best_school_option(
	options: List[SchoolOption],
	stored_url: Optional[str],
	stored_name: Optional[str],
	stored_number: Optional[str],
	username: Optional[str],
) -> Tuple[Optional[SchoolOption], List[Tuple[str, str, int, int, Optional[str]]]]:
	"""Choose the most suitable school option based on stored data and heuristics."""
	if not options:
		return (None, [])

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

	scored: List[Tuple[int, int, SchoolOption]] = []
	stored_school_found = False
	
	for idx, option in enumerate(options):
		lower_title = option.title.lower()
		lower_url = option.url.lower()
		score = 0

		# Check if this is the stored school
		is_stored_match = False
		if stored_number and option.number and option.number == stored_number:
			is_stored_match = True
			stored_school_found = True
		elif stored_url and option.url == stored_url:
			is_stored_match = True
			stored_school_found = True
		elif stored_name and stored_name.lower() == lower_title:
			is_stored_match = True
			stored_school_found = True
		
		# Give stored schools a boost, but not an automatic win
		# This allows better schools to override if the stored one is clearly wrong
		if is_stored_match:
			score += 500
			_LOGGER.debug(f"Found stored school match: '{option.title}' (+500 points)")

		if stored_name and stored_name.lower() == lower_title:
			score += 100  # Additional bonus for name match
		
		# Real kommun/municipality entries should score highest
		# Most users authenticate to their local kommun, not demo/test sites
		if 'kommun' in lower_title:
			score += 200  # Increased significantly - real municipalities
		
		# Penalize demo/test entries heavily - most users don't want these
		if 'övrigt' in lower_title or 'ovrigt' in lower_title:
			score -= 100  # Heavy penalty for "Other" entries
		if 'demo' in lower_title.lower() or 'demo' in lower_url:
			score -= 200  # Very heavy penalty for demo sites
		if 'test' in lower_title.lower() or '/test' in lower_url:
			score -= 150  # Heavy penalty for test sites
		
		# User type indicators (but lower priority than kommun)
		if 'elever' in lower_title or 'student' in lower_title or 'students' in lower_title:
			score += 30
		if 'vårdnadshavare' in lower_title or 'vardnadshavare' in lower_title or 'parent' in lower_title:
			score += 25
		if 'pupil' in lower_title:
			score += 20
		if 'personal' in lower_title or 'staff' in lower_title:
			score += 15
		
		# School type indicators
		if 'skola' in lower_title or 'school' in lower_title:
			score += 10
		if 'barn' in lower_title:
			score += 5
		if 'förskola' in lower_title or 'forskola' in lower_title:
			score += 5

		# URL scoring - prefer standard SSO URLs used by most municipalities
		if 'sso.infomentor.se/login.ashx?idp=' in lower_url:
			score += 150  # Standard kommun SSO URL pattern
		
		if 'ims-grandid-api.infomentor.se/login/initial' in lower_url:
			score += 120  # Alternative auth method for some kommuns
		
		if 'communeid' in lower_url:
			score += 30  # Commune ID parameter
		
		# Penalize non-production URLs
		if '/demo/' in lower_url:
			score -= 300  # Heavy penalty for demo URLs
		if 'test' in lower_url and 'mentor.is' in lower_url:
			score -= 250  # Heavy penalty for test environments
		if 'mentor.is' in lower_url and 'demo' not in lower_url and 'test' not in lower_url:
			score -= 50  # Slight penalty for .is domain (Icelandic, less common for Swedish users)
		
		# External IdP URLs (kommun-specific auth servers)
		if lower_url.startswith('https://idp') or '://idp' in lower_url:
			score += 100  # These are valid kommun-specific IdPs
		if 'chooseauthmech' in lower_url:
			score -= 5  # Slightly penalize if stuck at auth method selection

		# Username matching is not reliable for InfoMentor
		# All auth happens on infomentor.se domains, so email domain won't match
		# Only use username clues as a positive signal if they DO match (rare but possible)
		for clue in username_clues:
			if not clue:
				continue
			if clue in lower_url:
				score += 100  # Bonus if email domain happens to match URL
			elif clue in lower_title:
				score += 80  # Bonus if email domain happens to match title

		scored.append((score, idx, option))

	if not scored:
		return (None, [])

	ranked = sorted(scored, key=lambda item: (item[0], -item[1]), reverse=True)
	
	if not ranked:
		return (None, [])
	
	best_score, best_idx, best_option = ranked[0]
	
	# Log selection reasoning
	if stored_number or stored_url:
		if best_score >= 500:
			_LOGGER.info(f"Selected stored school (score {best_score}): '{best_option.title}' #{best_option.number}")
		else:
			_LOGGER.info(f"Selected different school despite stored preference (score {best_score}): '{best_option.title}' #{best_option.number}")
	else:
		_LOGGER.info(f"Selected school via scoring heuristics (score {best_score}): '{best_option.title}' #{best_option.number}")
	
	debug_scores = [
		(
			entry_option.title,
			entry_option.url,
			entry_score,
			order,
			entry_option.number,
		)
		for entry_score, order, entry_option in ranked
	]
	return (best_option, debug_scores)


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
		self._auth_cookies_backup: Optional[List[Dict[str, str]]] = None
		self._username: Optional[str] = None
		self._password: Optional[str] = None
		self._preferred_school_number: Optional[str] = None
		
	def _backup_auth_cookies(self) -> None:
		"""Snapshot InfoMentor cookies for reuse after a restart.

		Names like ASP.NET_SessionId exist on several InfoMentor hosts with
		different values, so each cookie is kept together with its domain.
		"""
		backup: List[Dict[str, str]] = []
		for cookie in self.session.cookie_jar:
			domain = (cookie["domain"] or "").lstrip(".")
			if domain == "infomentor.se" or domain.endswith(".infomentor.se"):
				backup.append({
					"domain": domain,
					"path": cookie["path"] or "/",
					"name": cookie.key,
					"value": cookie.value,
				})
		self._auth_cookies_backup = backup
		_LOGGER.debug(f"Backed up {len(backup)} auth cookies")
	
	def _restore_auth_cookies(self) -> bool:
		"""Put backed-up cookies back into the session jar, each on its own host."""
		# Older versions stored a flat {name: value} dict, which can't be restored reliably
		if not self._auth_cookies_backup or not isinstance(self._auth_cookies_backup, list):
			return False
		
		try:
			for cookie in self._auth_cookies_backup:
				self.session.cookie_jar.update_cookies(
					{cookie["name"]: cookie["value"]},
					response_url=URL(f"https://{cookie['domain']}{cookie.get('path') or '/'}"),
				)
			_LOGGER.debug(f"Restored {len(self._auth_cookies_backup)} authentication cookies")
			return True
		except Exception as e:
			_LOGGER.warning(f"Failed to restore auth cookies: {e}")
			return False
	
	async def try_restore_session(self) -> bool:
		"""Attempt to reuse stored cookies instead of running the full OAuth flow."""
		if not self.storage:
			return False
		
		try:
			cookies, saved_at = await self.storage.get_auth_cookies()
		except Exception as err:
			_LOGGER.debug(f"Could not load stored cookies: {err}")
			return False
		
		if not cookies:
			_LOGGER.debug("No stored InfoMentor cookies available for reuse")
			return False
		
		self._auth_cookies_backup = cookies
		if not self._restore_auth_cookies():
			_LOGGER.debug("Stored cookies could not be applied to the session")
			return False
		
		# _verify_authentication_status() also passes for a session without any
		# cookies, so require the hub to list the pupils, as after a real login
		try:
			self.pupil_ids = await self._get_pupil_ids_modern()
		except Exception as err:
			_LOGGER.debug(f"Pupil lookup with stored cookies failed: {err}")
			self.pupil_ids = []
		
		if self.pupil_ids:
			await self._build_switch_id_mapping()
			import time
			self.authenticated = True
			self._last_auth_time = time.time()
			_LOGGER.info("Reused stored InfoMentor cookies; skipping full authentication")
			return True
		
		_LOGGER.info("Stored InfoMentor cookies appear to be expired; clearing cache")
		self.session.cookie_jar.clear()
		await self.storage.clear_auth_cookies()
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
				# aiohttp yields http.cookies.Morsel objects: the name is .key, not ['name']
				name = getattr(cookie, 'key', '')
				if name in essential_cookies:
					found_cookies.append(name)
			except (KeyError, AttributeError, TypeError):
				# Skip problematic cookies
				continue
		
		if not found_cookies:
			_LOGGER.debug("No essential authentication cookies found")
			return True
		
		return False

	def _select_login_form(self, html_content: str) -> Optional[ParsedForm]:
		"""Select the most likely credential form from HTML content."""
		forms = parse_forms(html_content)
		assert forms is not None
		if not forms:
			return None
		return select_login_form(forms)

	def _resolve_form_action(self, base_url: str, action: Optional[str]) -> str:
		"""Resolve a form action relative to the base URL."""
		if not action:
			return base_url
		return _urljoin(base_url, html.unescape(action))

	def _get_origin(self, url: str) -> Optional[str]:
		"""Build the origin string for a URL."""
		try:
			parsed = urlparse(url)
			if parsed.scheme and parsed.netloc:
				return f"{parsed.scheme}://{parsed.netloc}"
		except Exception as err:
			_LOGGER.debug(f"Could not parse origin from url {url}: {err}")
		return None

	async def _fetch_login_page(self, url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[str, str, int]:
		"""Fetch a login page and return (text, final_url, status)."""
		use_headers = headers or DEFAULT_HEADERS.copy()
		await asyncio.sleep(REQUEST_DELAY)
		async with self.session.get(url, headers=use_headers, allow_redirects=True) as resp:
			text = await resp.text()
			return text, str(resp.url), resp.status

	def _ensure_form_field(self, form_fields: List[Tuple[str, str]], field_name: str, value: str) -> None:
		"""Ensure a form field is present with the provided value."""
		assert field_name
		for idx, (name, _) in enumerate(form_fields):
			if name == field_name:
				form_fields[idx] = (field_name, value)
				return
		form_fields.append((field_name, value))

	def _merge_hidden_fields(self, form_fields: List[Tuple[str, str]], html_content: str) -> int:
		"""Merge hidden inputs from raw HTML into the form fields."""
		added = 0
		hidden_fields = extract_hidden_fields(html_content)
		existing_names = {name for name, _ in form_fields}

		for name, value in hidden_fields:
			if name in existing_names:
				continue
			form_fields.append((name, value))
			existing_names.add(name)
			added += 1

		return added

	def _count_idp_fields(self, form_fields: List[Tuple[str, str]]) -> int:
		"""Count IdP list entries included in the form fields."""
		return sum(
			1
			for name, _ in form_fields
			if IDP_REPEATER_TOKEN in name and name.endswith("$url")
		)

	def _has_hub_payload(self, html_content: str) -> bool:
		"""Detect hub payload markers in HTML content."""
		return (
			"IMHome.home.homeData" in html_content
			or "IMHome.home.init" in html_content
			or "IMHome =" in html_content
		)

	async def _submit_parsed_form(
		self,
		form: ParsedForm,
		form_url: str,
		form_fields: List[Tuple[str, str]],
		referer: str,
	) -> Tuple[int, str, str]:
		"""Submit a parsed form and return (status, final_url, response_text)."""
		assert form_url
		assert isinstance(form_fields, list)

		headers = DEFAULT_HEADERS.copy()
		origin = self._get_origin(form_url)
		if origin:
			headers["Origin"] = origin
		headers["Referer"] = referer
		headers["Sec-Fetch-Dest"] = "document"
		headers["Sec-Fetch-Site"] = "same-origin"

		method = (form.method or "post").lower()
		enctype = (form.enctype or "").lower()
		is_multipart = "multipart/form-data" in enctype

		if method == "get":
			async with self.session.get(form_url, headers=headers, params=form_fields, allow_redirects=True) as resp:
				text = await resp.text()
				return resp.status, str(resp.url), text

		if is_multipart:
			form_data = aiohttp.FormData()
			for name, value in form_fields:
				form_data.add_field(name, value)
			payload = form_data
		else:
			headers["Content-Type"] = "application/x-www-form-urlencoded"
			payload = urlencode(form_fields)

		async with self.session.post(form_url, headers=headers, data=payload, allow_redirects=True) as resp:
			text = await resp.text()
			return resp.status, str(resp.url), text
	
	async def login(self, username: str, password: str) -> bool:
		"""Authenticate with InfoMentor using OAuth flow.
		
		Args:
			username: Username or email
			password: Password
			
		Returns:
			True if authentication successful
		"""
		_LOGGER.info("Login called for username=%s", username)
		try:
			_LOGGER.info("Starting InfoMentor OAuth authentication flow")
			# Store for potential reauthentication
			self._username = username
			self._password = password
			self._preferred_school_number = None
			
			if self.storage:
				try:
					_, _, stored_school_number = await self.storage.get_selected_school_details()
					if stored_school_number:
						self._preferred_school_number = stored_school_number
						self._apply_last_used_idp_cookie(stored_school_number)
						_LOGGER.debug(f"Applied stored IdP preference #{stored_school_number} to session")
				except Exception as pref_err:
					_LOGGER.debug(f"Could not apply stored IdP preference: {pref_err}")
			
			# Step 1: Get OAuth token (primary method)
			_LOGGER.info("Step 1: Getting OAuth token")
			try:
				oauth_token = await self._get_oauth_token()
				_LOGGER.info("OAuth token obtained: %s", bool(oauth_token))

				if oauth_token:
					_LOGGER.info("Step 2: Completing OAuth flow")
					await self._complete_oauth_to_modern_domain(oauth_token, username, password)
					_LOGGER.info("Step 2 completed")
				else:
					_LOGGER.warning("No OAuth token — trying direct login fallback")
					await self._direct_login_with_credentials(username, password)
			except Exception as oauth_err:
				_LOGGER.warning("OAuth flow failed (%s) — trying direct login fallback", oauth_err)
				try:
					await self._direct_login_with_credentials(username, password)
					_LOGGER.info("Direct login fallback completed")
				except Exception as fallback_err:
					_LOGGER.error("All login methods failed: oauth=%s, fallback=%s", oauth_err, fallback_err)
					raise oauth_err
			
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
				
				# Clear stored school preference since it's not working
				if self.storage and self._preferred_school_number:
					try:
						_LOGGER.warning(f"Clearing stored school preference #{self._preferred_school_number} because it returned no pupils")
						await self.storage.clear_selected_school()
						self._preferred_school_number = None
					except Exception as clear_err:
						_LOGGER.debug(f"Could not clear stored school preference: {clear_err}")
				
				# Don't mark as authenticated if we have no pupil IDs
				# This forces re-authentication on the next attempt
				_LOGGER.error("Authentication failed — no pupil IDs found")
				self.authenticated = False
				raise InfoMentorAuthError("Authentication failed - no pupil IDs found")
			else:
				_LOGGER.info("Authentication success — %d pupils found", len(self.pupil_ids))
				# Mark as authenticated and track timing
				self.authenticated = True
				import time
				self._last_auth_time = time.time()

				# Establish sessions on all domains so API calls work
				await self._establish_cross_domain_sessions()

				# Backup authentication cookies for potential restoration
				self._backup_auth_cookies()
				if self.storage and self._auth_cookies_backup:
					try:
						await self.storage.save_auth_cookies(self._auth_cookies_backup)
					except Exception as cookie_err:
						_LOGGER.debug(f"Could not persist auth cookies: {cookie_err}")

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
		login_url = OAUTH_LOGIN_URL
		last_text = ""
		last_url = login_url
		# Visit login page
		await asyncio.sleep(REQUEST_DELAY)
		async with self.session.get(login_url, headers=headers, allow_redirects=True) as resp:
			last_text = await resp.text()
			last_url = str(resp.url)
			_LOGGER.debug(f"Login page status={resp.status}, url={last_url}")
		# Handle auto-submit if present
		if _has_openid_form(last_text):
			_LOGGER.debug("Auto-submit form detected on login page; submitting...")
			result = await _auto_submit_openid_form(self.session, last_text, referer=last_url)
			if result.executed:
				last_text = result.final_text or last_text
				last_url = result.final_url or last_url
		# If a credential form is present, submit credentials
		login_form = self._select_login_form(last_text)
		if login_form:
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
		oauth_url = OAUTH_LOGIN_URL_WITH_INSTANCE
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
				if _has_openid_form(text):
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
			_LOGGER.info("Starting OAuth completion: posting token to legacy portal")

			headers = DEFAULT_HEADERS.copy()
			headers.update({
				"Content-Type": "application/x-www-form-urlencoded",
				"Origin": HUB_BASE_URL,
				"Referer": f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true",
				"Sec-Fetch-Site": "cross-site",
				"Sec-Fetch-Dest": "document",
			})

			oauth_data = f"oauth_token={oauth_token}"

			await asyncio.sleep(REQUEST_DELAY)
			async with self.session.post(
				LEGACY_BASE_URL,
				headers=headers,
				data=oauth_data,
				allow_redirects=True,
			) as resp:
				stage1_text = await resp.text()
				_LOGGER.info("Stage 1 response: status=%s url=%s (%d chars)", resp.status, resp.url, len(stage1_text))

				await _write_text_file_async(DEBUG_FILE_OAUTH, stage1_text)

				if "LoginCallback" in str(resp.url):
					_LOGGER.info("Received early LoginCallback")
					await self._handle_login_callback(str(resp.url), stage1_text)
					return
			
			# Some flows render auto-submit form here; handle it
			if _has_openid_form(stage1_text):
				_LOGGER.info("Detected auto-submit form during stage 1; submitting...")
				result = await _auto_submit_openid_form(self.session, stage1_text, referer=str(resp.url))
				if result.executed:
					stage1_text = result.final_text or stage1_text
					_LOGGER.info("Stage 1 auto-submit form completed")
					if result.final_url and "LoginCallback" in result.final_url:
						await self._handle_login_callback(result.final_url, stage1_text)
						return
				else:
					_LOGGER.warning("Stage 1 auto-submit form failed")

			if "IdpListRepeater" in stage1_text:
				_LOGGER.debug("School selection fields present in form (will be submitted with credentials)")

			login_form = self._select_login_form(stage1_text)
			_LOGGER.info("Credential form found: %s", bool(login_form))
			if login_form:
				await self._submit_credentials_and_handle_second_oauth(stage1_text, username, password, str(resp.url))
				_LOGGER.info("Credential submission completed")
			else:
				_LOGGER.warning("No credential form found in stage 1 response (%d chars)", len(stage1_text))
		except Exception as oauth_completion_err:
			_LOGGER.error("OAuth completion failed: %s", oauth_completion_err)
			raise
	
	async def _handle_login_callback(self, callback_url: str, response_text: str) -> None:
		"""Handle LoginCallback URL with oauth_token and oauth_verifier."""
		_LOGGER.debug(f"*** HANDLING LOGINCALLBACK v0.0.53 *** {callback_url}")
		
		# Parse the callback URL to extract OAuth parameters
		parsed_url = urlparse(callback_url)
		query_params = parse_qs(parsed_url.query)
		
		oauth_token = query_params.get('oauth_token', [None])[0]
		oauth_verifier = query_params.get('oauth_verifier', [None])[0]
		
		_LOGGER.debug(f"*** CALLBACK OAUTH TOKEN v0.0.53 *** {oauth_token[:20] if oauth_token else 'None'}...")
		_LOGGER.debug(f"*** CALLBACK OAUTH VERIFIER v0.0.53 *** {oauth_verifier[:20] if oauth_verifier else 'None'}...")
		
		if not oauth_token or not oauth_verifier:
			_LOGGER.warning("*** INCOMPLETE OAUTH CALLBACK - MISSING TOKEN OR VERIFIER v0.0.53 ***")
			return
		
		# Save the callback response for debugging
		await _write_text_file_async("/tmp/infomentor_oauth_callback.html", response_text)
		_LOGGER.debug("*** SAVED OAUTH CALLBACK DEBUG FILE v0.0.53 ***")
		
		# Check if the callback response already contains pupil data
		if any(indicator in response_text.lower() for indicator in ['pupil', 'elev', 'student', 'dashboard']):
			_LOGGER.debug("*** CALLBACK CONTAINS PUPIL DATA v0.0.53 ***")
		else:
			_LOGGER.debug("*** CALLBACK REQUIRES ADDITIONAL PROCESSING v0.0.53 ***")
			
			# Try to navigate to the dashboard using the callback parameters
			await self._navigate_to_dashboard_with_oauth_params(oauth_token, oauth_verifier)
	
	async def _navigate_to_dashboard_with_oauth_params(self, oauth_token: str, oauth_verifier: str) -> None:
		"""Navigate to dashboard using OAuth token and verifier."""
		_LOGGER.debug("*** NAVIGATING TO DASHBOARD WITH OAUTH PARAMS v0.0.53 ***")
		
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
				_LOGGER.debug(f"*** TRYING DASHBOARD URL v0.0.53 *** {dashboard_url}")
				async with self.session.get(dashboard_url, headers=headers, allow_redirects=True) as resp:
					dashboard_text = await resp.text()
					_LOGGER.debug(f"*** DASHBOARD RESPONSE v0.0.53 *** {resp.status} -> {resp.url}")
					
					# Check if this contains pupil data
					if any(indicator in dashboard_text.lower() for indicator in ['pupil', 'elev', 'student']):
						_LOGGER.debug("*** FOUND PUPIL DATA IN DASHBOARD v0.0.53 ***")
						await _write_text_file_async("/tmp/infomentor_oauth_dashboard.html", dashboard_text)
						break
					elif "login" in dashboard_text.lower() or "authentication" in dashboard_text.lower():
						_LOGGER.debug("*** DASHBOARD REQUIRES ADDITIONAL AUTH v0.0.53 ***")
						continue
					else:
						_LOGGER.debug("*** DASHBOARD STATUS UNCLEAR v0.0.53 ***")
						
			except Exception as e:
				_LOGGER.warning(f"*** DASHBOARD NAVIGATION ERROR v0.0.53 *** {e}")
				continue
	
	async def _submit_credentials_and_handle_second_oauth(self, form_html: str, username: str, password: str, form_url: str) -> None:
		"""Submit credentials and handle the second OAuth token."""
		_LOGGER.debug("Submitting credentials for two-stage OAuth")

		if not form_html:
			raise InfoMentorAuthError("Missing login form HTML for credential submission")

		used_html = form_html
		used_url = form_url
		login_form = self._select_login_form(form_html)

		if not login_form:
			_LOGGER.warning("Login form not found in initial response; reloading login page")
			try:
				refreshed_html, refreshed_url, _ = await self._fetch_login_page(form_url)
				used_html = refreshed_html
				used_url = refreshed_url
				login_form = self._select_login_form(refreshed_html)
			except Exception as refresh_err:
				_LOGGER.debug(f"Refreshing login page failed: {refresh_err}")

		if not login_form:
			_LOGGER.warning("Could not locate login form for credential submission (%d chars)", len(used_html))
			raise InfoMentorAuthError("Could not locate login form for credential submission")

		form_action_url = self._resolve_form_action(used_url, login_form.action)
		form_fields, username_field, password_field, submit_field = build_login_form_data(
			login_form,
			username,
			password,
		)
		field_names = [name for name, _ in form_fields]
		idp_field_count = self._count_idp_fields(form_fields)
		viewstate_present = VIEWSTATE_FIELD in field_names

		if (IDP_REPEATER_TOKEN in used_html and idp_field_count == 0) or not viewstate_present:
			added = self._merge_hidden_fields(form_fields, used_html)
			field_names = [name for name, _ in form_fields]
			idp_field_count = self._count_idp_fields(form_fields)
			viewstate_present = VIEWSTATE_FIELD in field_names
			_LOGGER.info(
				"Augmented login payload with %s hidden fields; idp_list=%s viewstate=%s",
				added,
				idp_field_count,
				viewstate_present,
			)

		if submit_field:
			if EVENTTARGET_FIELD in field_names or EVENTTARGET_FIELD in used_html:
				self._ensure_form_field(form_fields, EVENTTARGET_FIELD, submit_field)
			if EVENTARGUMENT_FIELD in field_names or EVENTARGUMENT_FIELD in used_html:
				self._ensure_form_field(form_fields, EVENTARGUMENT_FIELD, "")

		assert form_action_url
		assert isinstance(form_fields, list)

		if not username_field or not password_field:
			_LOGGER.warning("Could not identify username/password fields in login form at %s", form_action_url)
			raise InfoMentorAuthError("Could not identify username/password fields in login form")

		_LOGGER.info(f"Extracted {len(form_fields)} form fields (including non-hidden fields)")
		_LOGGER.debug(
			f"Login fields detected: username={username_field}, password={password_field}, submit={submit_field}"
		)
		viewstate_value = next((value for name, value in form_fields if name == VIEWSTATE_FIELD), "")
		if viewstate_value:
			_LOGGER.debug(f"Viewstate length: {len(viewstate_value)}")

		await asyncio.sleep(REQUEST_DELAY)
		status, final_url, cred_text = await self._submit_parsed_form(
			login_form,
			form_action_url,
			form_fields,
			used_url,
		)
		_LOGGER.info("Credential submission response: status=%s url=%s", status, final_url)

		if "LoginCallback" in final_url:
			_LOGGER.info("Credentials led to LoginCallback")
			await self._handle_login_callback(final_url, cred_text)
			return

		# Check for credential rejection first
		if self._select_login_form(cred_text):
			_LOGGER.warning("Credentials appear to have been rejected — login form still present")
			raise InfoMentorAuthError("Invalid credentials - login form still present after submission")

		# --- Critical step: detect WS-Fed / OpenID auto-submit form ---
		# A real browser would auto-submit this form back to the hub callback,
		# carrying wresult/wa/wctx/oauth_token fields that establish the hub session.
		if _has_openid_form(cred_text):
			_LOGGER.info("Credential response contains OpenID auto-submit form — following it back to hub")
			result = await _auto_submit_openid_form(self.session, cred_text, referer=final_url)
			if result.executed:
				_LOGGER.info("OpenID auto-submit after credentials completed; final_url=%s", result.final_url)
				if result.final_url and "LoginCallback" in result.final_url:
					await self._handle_login_callback(result.final_url, result.final_text or "")
				return
			_LOGGER.warning("OpenID auto-submit after credentials did not execute — falling through")

		# Fallback: look for a bare oauth_token hidden field (older flow)
		second_oauth_match = re.search(r'oauth_token"\s+value="([\w+=/]+)"', cred_text)
		if second_oauth_match:
			second_oauth_token = second_oauth_match.group(1)
			_LOGGER.info("Found second OAuth token (fallback path) — submitting")
			await self._submit_second_oauth_token(second_oauth_token)
		else:
			success_indicators = [
				"default.aspx" in final_url.lower(),
				"hub.infomentor.se" in final_url.lower(),
				"logout" in cred_text.lower(),
				"dashboard" in cred_text.lower(),
			]
			if any(success_indicators):
				_LOGGER.info("Credentials accepted without second OAuth token")
			else:
				_LOGGER.warning("Post-credential authentication state unclear")
	
	async def _submit_second_oauth_token(self, oauth_token: str) -> None:
		"""Submit the second OAuth token to complete authentication.

		Posts the token to the legacy portal.  If the response is another
		OpenID auto-submit form (pointing back to the hub), follow it so
		the hub session is properly established.
		"""
		_LOGGER.info("Submitting second OAuth token to legacy portal")

		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Content-Type": "application/x-www-form-urlencoded",
			"Origin": "https://infomentor.se",
			"Referer": LEGACY_BASE_URL,
			"Sec-Fetch-Site": "same-origin",
			"Sec-Fetch-Dest": "document",
		})

		oauth_data = f"oauth_token={oauth_token}"

		async with self.session.post(
			LEGACY_BASE_URL,
			headers=headers,
			data=oauth_data,
			allow_redirects=True,
		) as resp:
			final_text = await resp.text()
			resp_url = str(resp.url)
			_LOGGER.info("Second OAuth response: status=%s url=%s (%d chars)", resp.status, resp_url, len(final_text))

			if "LoginCallback" in resp_url:
				await self._handle_login_callback(resp_url, final_text)
				return

			# If the response is an OpenID form heading back to the hub, follow it
			if _has_openid_form(final_text):
				_LOGGER.info("Second OAuth returned OpenID form — auto-submitting back to hub")
				result = await _auto_submit_openid_form(self.session, final_text, referer=resp_url)
				if result.executed:
					_LOGGER.info("Hub round-trip completed; final_url=%s", result.final_url)
					if result.final_url and "LoginCallback" in result.final_url:
						await self._handle_login_callback(result.final_url, result.final_text or "")
					return

			# Touch the hub root to propagate cookies across domains
			try:
				hub_headers = DEFAULT_HEADERS.copy()
				hub_headers["Referer"] = resp_url
				async with self.session.get(f"{HUB_BASE_URL}/", headers=hub_headers, allow_redirects=True) as hub_resp:
					hub_text = await hub_resp.text()
					# If the hub root itself is an auto-submit form, follow it too
					if _has_openid_form(hub_text):
						result = await _auto_submit_openid_form(self.session, hub_text, referer=str(hub_resp.url))
						if result.executed:
							_LOGGER.info("Hub root auto-submit completed; final_url=%s", result.final_url)
					else:
						_LOGGER.debug("Touched hub root, status=%s (%d chars)", hub_resp.status, len(hub_text))
			except Exception as e_touch:
				_LOGGER.debug("Touching hub root failed: %s", e_touch)

			await self._verify_authentication_status()
	
	def _apply_last_used_idp_cookie(self, school_number: Optional[str]) -> None:
		"""Mirror browser behaviour by persisting the last IdP selection cookie."""
		if not school_number or not self.session:
			return
		
		try:
			self.session.cookie_jar.update_cookies(
				{"Im1_Ck_LastUsedIdp": str(school_number)},
				response_url="https://infomentor.se/swedish/production/mentor/",
			)
			_LOGGER.debug(f"Set Im1_Ck_LastUsedIdp cookie to {school_number}")
		except Exception as cookie_err:
			_LOGGER.debug(f"Unable to set Im1_Ck_LastUsedIdp cookie: {cookie_err}")
	
	async def _handle_school_selection(self, html: str, referer: str) -> None:
		"""Handle automatic school/municipality selection."""
		_LOGGER.info("*** PROCESSING SCHOOL SELECTION v0.0.90 ***")
		
		import re as _re
		
		# First, check if we have a previously selected school preference
		stored_school_url = None
		stored_school_name = None
		stored_school_number = self._preferred_school_number
		if self.storage:
			try:
				stored_school_url, stored_school_name, stored_school_number = await self.storage.get_selected_school_details()
				if stored_school_url or stored_school_name or stored_school_number:
					_LOGGER.info(
						f"*** FOUND STORED SCHOOL PREFERENCE v0.0.90 *** "
						f"url={stored_school_url} name={stored_school_name} number={stored_school_number}"
					)
			except Exception as e:
				_LOGGER.debug(f"Could not load stored school preference: {e}")
		
		# Extract all school options from the selection page
		# Look for input fields with URLs and their corresponding titles
		url_pattern = r'<input[^>]*name=["\']login_ascx\$IdpListRepeater\$ctl(\d+)\$url["\'][^>]*value=["\']([^"\']*)["\']'
		url_matches = _re.findall(url_pattern, html, _re.IGNORECASE)
		
		_LOGGER.debug(f"*** FOUND {len(url_matches)} SCHOOL OPTIONS v0.0.76 ***")
		
		# Save school selection page for debugging
		await _write_text_file_async("/tmp/infomentor_school_selection.html", html)
		_LOGGER.debug("*** SAVED SCHOOL SELECTION PAGE v0.0.76 *** /tmp/infomentor_school_selection.html")
		
		# Log all available schools for debugging
		school_options: List[SchoolOption] = []
		for control_id, url in url_matches:
			title_pattern = f'<span[^>]*id=["\']login_ascx_IdpListRepeater_ctl{control_id}_title["\'][^>]*>([^<]+)</span>'
			title_match = _re.search(title_pattern, html, _re.IGNORECASE)
			if title_match:
				import html as html_module
				raw_title = title_match.group(1).strip()
				title = html_module.unescape(raw_title)
				decoded_url = html_module.unescape(url.strip())
				number_pattern = f'<input[^>]*name=["\']login_ascx\\$IdpListRepeater\\$ctl{control_id}\\$number["\'][^>]*value=["\']([^"\']*)["\']'
				number_match = _re.search(number_pattern, html, _re.IGNORECASE)
				school_number = html_module.unescape(number_match.group(1).strip()) if number_match else None
				option = SchoolOption(title=title, url=decoded_url, number=school_number)
				school_options.append(option)
				_LOGGER.debug(f"*** AVAILABLE SCHOOL v0.0.90 *** [{control_id}] #{school_number or 'n/a'}: '{title}' -> {decoded_url}")
		
		selected_option, scored_options = _choose_best_school_option(
			school_options,
			stored_school_url,
			stored_school_name,
			stored_school_number,
			self._username,
		)
		
		if scored_options:
			for rank, (title, url, score, order, number) in enumerate(scored_options[:5], start=1):
				_LOGGER.debug(
					f"*** SCHOOL SCORECARD v0.0.90 *** rank={rank} score={score} order={order} "
					f"number={number} '{title}' -> {url}"
				)
		
		if not selected_option:
			_LOGGER.warning("No suitable school found in selection page")
			return
		
		school_name = selected_option.title
		school_url = selected_option.url
		school_number = selected_option.number
		_LOGGER.debug(f"*** CHOSEN SCHOOL v0.0.90 *** {school_name} -> {school_url}")
		if school_number:
			self._preferred_school_number = school_number
			self._apply_last_used_idp_cookie(school_number)
		
		# Navigate to the selected school's authentication URL
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Referer": referer,
		})
		
		# Save the selected school for future use
		if self.storage and school_url and school_name:
			try:
				await self.storage.save_selected_school_url(school_url, school_name, school_number)
			except Exception as e:
				_LOGGER.debug(f"Could not save selected school: {e}")
		
		try:
			await asyncio.sleep(REQUEST_DELAY)
			_LOGGER.debug(f"*** ATTEMPTING SCHOOL SELECTION v0.0.75 *** {school_name} -> {school_url}")
			
			# Try with a shorter timeout and better error handling
			timeout = aiohttp.ClientTimeout(total=10)
			async with self.session.get(school_url, headers=headers, allow_redirects=True, timeout=timeout) as resp:
				_LOGGER.debug(f"*** SCHOOL SELECTION SUCCESS v0.0.75 *** {resp.status} -> {resp.url}")
				selection_text = await resp.text()
				
				# Handle authentication method selection page immediately
				_LOGGER.debug(f"*** AUTH METHOD CHECK v0.0.47 *** chooseAuthmech: {'chooseAuthmech' in str(resp.url)}")
				_LOGGER.debug(f"*** PAGE CONTENT SAMPLE v0.0.47 *** {selection_text[:1000]}...")
				_LOGGER.debug(f"*** PAGE CONTENT LENGTH v0.0.47 *** {len(selection_text)} chars")
				
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
				_LOGGER.debug(f"*** FOUND AUTH INDICATORS v0.0.48 *** {found_indicators}")
				
				# Check for password option with HTML entities and encodings
				password_indicators = ["Lösenord", "Password", "L%C3%B6senord", "L&#246;senord", "L&#37;c3&#37;b6senord", "lösenord", "password"]
				has_password_option = any(indicator in selection_text for indicator in password_indicators)
				_LOGGER.debug(f"*** PASSWORD OPTION CHECK v0.0.48 *** {has_password_option}")
				
				if "chooseAuthmech" in str(resp.url):
					if has_password_option:
						_LOGGER.debug("*** DETECTED AUTH METHOD SELECTION v0.0.47 ***")
						await self._handle_auth_method_selection(selection_text, str(resp.url))
					else:
						# Fallback: Try to construct password URL from URL parameters
						_LOGGER.debug("*** NO PASSWORD IN CONTENT - TRYING URL FALLBACK v0.0.47 ***")
						if "L%C3%B6senord" in str(resp.url):
							await self._handle_auth_method_fallback(str(resp.url))
					# Note: Don't return here, let the flow continue to check for more redirects
				elif _has_openid_form(selection_text):
					_LOGGER.info("School returned auto-submit form")
					form_result = await _auto_submit_openid_form(self.session, selection_text, str(resp.url))
					if form_result.executed:
						_LOGGER.debug("*** SCHOOL AUTO-SUBMIT COMPLETED v0.0.43 ***")
					
		except Exception as e:
			_LOGGER.error("School selection failed: %s", e)
			_LOGGER.warning(f"*** PROBLEMATIC URL v0.0.43 *** {school_url}")
			
			# If school selection fails, try to continue without it
			# Some accounts might not need explicit school selection
			_LOGGER.debug("*** CONTINUING WITHOUT SCHOOL SELECTION v0.0.43 ***")

	async def _handle_auth_method_selection(self, html: str, page_url: str) -> None:
		"""Handle authentication method selection by choosing password login."""
		_LOGGER.debug("*** PROCESSING AUTH METHOD SELECTION v0.0.44 ***")
		
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
				_LOGGER.debug(f"*** FOUND PASSWORD LINK PATTERN v0.0.46 *** {pattern}")
				break
		
		if password_match:
			password_url = password_match.group(1)
			
			# CRITICAL: Decode HTML entities in the URL before using it
			# The URL often contains things like &#37;c3&#37;b6 which need to be decoded
			import html
			password_url = html.unescape(password_url)
			_LOGGER.debug(f"*** DECODED PASSWORD URL v0.0.79 *** {password_url}")
			
			# Handle relative URLs
			from urllib.parse import urljoin
			if password_url.startswith('/'):
				password_url = urljoin(page_url, password_url)
			elif not password_url.startswith('http'):
				# Relative path without leading slash
				base_url = '/'.join(page_url.split('/')[:-1]) + '/'
				password_url = urljoin(base_url, password_url)
			
			_LOGGER.debug(f"*** SELECTING PASSWORD AUTH METHOD v0.0.79 *** {password_url}")
			
			headers = DEFAULT_HEADERS.copy()
			headers.update({
				"Referer": page_url,
			})
			
			try:
				await asyncio.sleep(REQUEST_DELAY)
				async with self.session.get(password_url, headers=headers, allow_redirects=True) as resp:
					_LOGGER.debug(f"*** AUTH METHOD SELECTION RESULT v0.0.44 *** {resp.status} -> {resp.url}")
					
					auth_method_text = await resp.text()
					
					# Handle any auto-submit forms that might appear
					if _has_openid_form(auth_method_text):
						_LOGGER.info("Auth method returned auto-submit form")
						form_result = await _auto_submit_openid_form(self.session, auth_method_text, str(resp.url))
						if form_result.executed:
							_LOGGER.debug("*** AUTH METHOD AUTO-SUBMIT COMPLETED v0.0.44 ***")
					
			except Exception as e:
				_LOGGER.warning(f"*** AUTH METHOD SELECTION FAILED v0.0.44 *** {e}")
		else:
			_LOGGER.warning("*** NO PASSWORD AUTH METHOD FOUND v0.0.44 ***")
			_LOGGER.debug(f"*** AUTH METHOD PAGE SNIPPET v0.0.44 *** {html[:500]}...")

	async def _handle_auth_method_fallback(self, page_url: str) -> None:
		"""Fallback method to handle authentication method selection by constructing URL directly."""
		_LOGGER.debug("*** PROCESSING AUTH METHOD FALLBACK v0.0.47 ***")
		
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
				_LOGGER.debug(f"*** TRYING FALLBACK URL v0.0.47 *** {password_url}")
				await asyncio.sleep(REQUEST_DELAY)
				
				async with self.session.get(password_url, headers=headers, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as resp:
					if resp.status == 200:
						_LOGGER.debug(f"*** FALLBACK URL SUCCESS v0.0.47 *** {resp.status} -> {resp.url}")
						auth_result_text = await resp.text()
						
						# Check if this led to a login form or another redirect
						if any(field in auth_result_text.lower() for field in ['txtnotandanafn', 'txtlykilord', 'password', 'username']):
							_LOGGER.debug("*** FALLBACK LED TO LOGIN FORM v0.0.47 ***")
							return  # Success - let the normal flow handle the login form
						elif _has_openid_form(auth_result_text):
							_LOGGER.info("Fallback returned auto-submit form")
							form_result = await _auto_submit_openid_form(self.session, auth_result_text, str(resp.url))
							if form_result.executed:
								_LOGGER.debug("*** FALLBACK AUTO-SUBMIT COMPLETED v0.0.47 ***")
								return
						else:
							_LOGGER.debug(f"*** FALLBACK URL UNCLEAR RESULT v0.0.47 *** {auth_result_text[:200]}...")
					else:
						_LOGGER.warning(f"*** FALLBACK URL FAILED v0.0.47 *** {resp.status}")
						
			except Exception as e:
				_LOGGER.warning(f"*** FALLBACK URL EXCEPTION v0.0.47 *** {password_url} -> {e}")
				continue
		
		_LOGGER.warning("*** ALL FALLBACK URLS FAILED v0.0.47 ***")

	async def _direct_login_with_credentials(self, username: str, password: str) -> None:
		"""Login directly using username/password on the main InfoMentor login page."""
		_LOGGER.debug("*** STARTING DIRECT LOGIN v0.0.51 ***")

		login_url = LEGACY_BASE_URL
		headers = DEFAULT_HEADERS.copy()

		try:
			login_page, final_login_url, status = await self._fetch_login_page(login_url, headers)
			_LOGGER.debug(f"*** LOGIN PAGE RESPONSE v0.0.51 *** {status} -> {final_login_url}")
			_LOGGER.debug(f"*** LOGIN PAGE LENGTH v0.0.51 *** {len(login_page)} chars")

			await _write_text_file_async("/tmp/infomentor_login_page.html", login_page)
			_LOGGER.debug("*** SAVED LOGIN PAGE v0.0.51 *** /tmp/infomentor_login_page.html")

			login_form = self._select_login_form(login_page)
			if not login_form:
				_LOGGER.error("No login form found on main page")
				raise InfoMentorAuthError("Could not find login form on main page")

			form_action_url = self._resolve_form_action(final_login_url, login_form.action)
			form_fields, username_field, password_field, submit_field = build_login_form_data(
				login_form,
				username,
				password,
			)

			if not username_field or not password_field:
				_LOGGER.error("Could not identify login fields in form")
				raise InfoMentorAuthError("Could not find username/password fields")

			field_names = [name for name, _ in form_fields]
			_LOGGER.debug(
				f"*** LOGIN FIELDS v0.0.51 *** username={username_field}, password={password_field}, submit={submit_field}"
			)
			_LOGGER.debug(f"*** SUBMITTING LOGIN FORM v0.0.51 *** {form_action_url}")
			_LOGGER.debug(f"*** FORM FIELD COUNT v0.0.51 *** {len(field_names)}")
			_LOGGER.debug(f"*** FORM FIELD SAMPLE v0.0.51 *** {field_names[:15]}")

			await asyncio.sleep(REQUEST_DELAY)
			status, final_url, login_result = await self._submit_parsed_form(
				login_form,
				form_action_url,
				form_fields,
				final_login_url,
			)
			_LOGGER.debug(f"*** LOGIN RESULT v0.0.51 *** {status} -> {final_url}")
			_LOGGER.debug(f"*** LOGIN RESULT LENGTH v0.0.51 *** {len(login_result)} chars")

			await _write_text_file_async("/tmp/infomentor_login_result.html", login_result)
			_LOGGER.debug("*** SAVED LOGIN RESULT v0.0.51 *** /tmp/infomentor_login_result.html")

			success_indicators = [
				"student-menu",
				"pupil-selection",
				"dashboard",
				"mentor-main",
				"logout",
				"logga ut",
			]

			is_success = any(indicator in login_result.lower() for indicator in success_indicators)

			if is_success:
				_LOGGER.debug("*** DIRECT LOGIN SUCCESS v0.0.51 ***")
			else:
				error_indicators = [
					"felaktigt",
					"error",
					"failed",
					"invalid",
					"wrong",
				]

				has_error = any(indicator in login_result.lower() for indicator in error_indicators)

				if has_error:
					_LOGGER.error("Direct login failed — invalid credentials")
					raise InfoMentorAuthError("Invalid username or password")
				else:
					_LOGGER.debug("*** DIRECT LOGIN UNCLEAR RESULT v0.0.51 ***")
					_LOGGER.debug(f"*** RESULT SAMPLE v0.0.51 *** {login_result[:500]}...")

		except Exception as e:
			_LOGGER.error("Direct login exception: %s", e)
			raise

	async def _verify_authentication_status(self) -> bool:
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
							return True
			except Exception as e:
				_LOGGER.debug(f"Failed to verify authentication via {endpoint}: {e}")
				continue
		
		# If we get here, authentication verification failed
		_LOGGER.warning("Could not verify authentication status - OAuth may have failed")
		return False
	
	async def _establish_cross_domain_sessions(self) -> None:
		"""Visit key InfoMentor domains after auth to propagate session cookies.

		The OAuth/WS-Fed flow establishes cookies on hub.infomentor.se, but
		API calls to im.infomentor.se and legacy infomentor.se need their own
		cookies.  Visiting each domain with allow_redirects lets the server
		issue the necessary set-cookie headers, mirroring what a browser does
		when the SPA loads resources from multiple subdomains.
		"""
		domains_to_visit = [
			(f"{MODERN_BASE_URL}/", "im.infomentor.se"),
			(f"{HUB_BASE_URL}/", "hub.infomentor.se"),
			(f"{LEGACY_BASE_URL}", "legacy infomentor.se"),
		]

		headers = DEFAULT_HEADERS.copy()
		headers["Referer"] = f"{HUB_BASE_URL}/"

		for url, label in domains_to_visit:
			try:
				await asyncio.sleep(REQUEST_DELAY)
				async with self.session.get(url, headers=headers, allow_redirects=True) as resp:
					body = await resp.text()

					if _has_openid_form(body):
						result = await _auto_submit_openid_form(self.session, body, referer=str(resp.url))
						if result.executed:
							_LOGGER.debug("Cross-domain auto-submit completed for %s", label)

					_LOGGER.debug(
						"Cross-domain session visit to %s: status=%s cookies_after=%d",
						label, resp.status,
						sum(1 for _ in self.session.cookie_jar),
					)
			except Exception as err:
				_LOGGER.debug("Cross-domain session visit to %s failed: %s", label, err)

	async def _try_alternative_hub_access(self, headers: dict) -> None:
		"""Try alternative methods to access the hub dashboard."""
		_LOGGER.debug("*** TRYING ALTERNATIVE HUB ACCESS v0.0.53 ***")
		
		# List of alternative URLs to try
		alternative_urls = [
			f"{HUB_BASE_URL}/home",
			f"{HUB_BASE_URL}/start", 
			f"{HUB_BASE_URL}/dashboard",
			f"{HUB_BASE_URL}/account",
		]
		
		for alt_url in alternative_urls:
			try:
				_LOGGER.debug(f"*** TRYING ALTERNATIVE URL v0.0.53 *** {alt_url}")
				await asyncio.sleep(REQUEST_DELAY)
				async with self.session.get(alt_url, headers=headers, allow_redirects=True) as resp:
					_LOGGER.debug(f"*** ALTERNATIVE URL RESPONSE v0.0.53 *** {resp.status} -> {resp.url}")
					
					# If we get a good response without auto-submit, we might have found the right path
					alt_text = await resp.text()
					if len(alt_text) > 10000 and not _has_openid_form(alt_text):
						_LOGGER.debug(f"*** FOUND GOOD ALTERNATIVE v0.0.53 *** {alt_url} -> {len(alt_text)} chars")
						await _write_text_file_async(f"/tmp/infomentor_hub_alt_{alt_url.split('/')[-1]}.html", alt_text)
						break
			except Exception as e:
				_LOGGER.warning(f"*** ALTERNATIVE URL ERROR v0.0.53 *** {alt_url}: {e}")
				continue
	
	async def _get_pupil_ids_modern(self) -> list[str]:
		"""Get pupil IDs from modern InfoMentor Hub interface."""
		_LOGGER.info("Getting pupil IDs from hub")
		
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
				_LOGGER.info("Hub dashboard: status=%s (%d chars)", resp.status, 0)
				text = await resp.text()
				_LOGGER.info("Hub dashboard content length: %d", len(text))

				await _write_text_file_async("/tmp/infomentor_hub_dashboard.html", text)

				if _has_openid_form(text):
					auto_submit_attempts += 1
					_LOGGER.info("Hub returned auto-submit form (attempt %d/%d, %d chars)", auto_submit_attempts, max_auto_submit_attempts, len(text))
					_LOGGER.debug(f"*** CONTENT LENGTH IS ONLY {len(text)} - NEED TO GET REAL HUB v0.0.64 ***")
					
					# Prevent infinite auto-submit loops
					if auto_submit_attempts > max_auto_submit_attempts:
						_LOGGER.error("Auto-submit loop detected — stopping after %d attempts", auto_submit_attempts)
						raise InfoMentorAuthError("Auto-submit loop detected - authentication failed")
					
					# Check if the auto-submit would take us to legacy interface
					action_match = re.search(r'action=["\']([^"\']+)["\']', text, re.IGNORECASE)
					if action_match:
						action_url = action_match.group(1)
						_LOGGER.debug(f"*** AUTO-SUBMIT ACTION URL v0.0.64 *** {action_url}")
						
						# If it would take us to legacy, try alternative approaches first
						if "infomentor.se/swedish/production/mentor" in action_url.lower():
							_LOGGER.debug("*** AUTO-SUBMIT LEADS TO LEGACY - TRYING ALTERNATIVES v0.0.64 ***")
							
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
									_LOGGER.debug(f"*** TRYING HUB ALTERNATIVE v0.0.55 *** {alt_url}")
									await asyncio.sleep(REQUEST_DELAY)
									async with self.session.get(alt_url, headers=headers, allow_redirects=True) as alt_resp:
										alt_text = await alt_resp.text()
										_LOGGER.debug(f"*** ALTERNATIVE RESULT v0.0.55 *** {alt_resp.status} -> {len(alt_text)} chars")
										
										# If we get substantial content without auto-submit, use it
										if len(alt_text) > 10000 and not _has_openid_form(alt_text):
											_LOGGER.debug(f"*** FOUND REAL HUB CONTENT v0.0.55 *** {alt_url}")
											text = alt_text
											found_real_hub = True
											await _write_text_file_async("/tmp/infomentor_hub_alternative_success.html", text)
											break
								except Exception as e:
									_LOGGER.warning(f"*** ALTERNATIVE ERROR v0.0.55 *** {alt_url}: {e}")
									continue
							
							# Strategy 2: If alternatives failed, wait and retry main hub URL
							if not found_real_hub:
								_LOGGER.debug("*** ALTERNATIVES FAILED - WAITING AND RETRYING MAIN HUB v0.0.55 ***")
								await asyncio.sleep(REQUEST_DELAY * 3)  # Wait longer
								async with self.session.get(dashboard_url, headers=headers) as retry_resp:
									retry_text = await retry_resp.text()
									_LOGGER.debug(f"*** RETRY RESULT v0.0.55 *** {retry_resp.status} -> {len(retry_text)} chars")
									
									if len(retry_text) > 10000 and not _has_openid_form(retry_text):
										_LOGGER.debug("*** RETRY FOUND REAL HUB CONTENT v0.0.55 ***")
										text = retry_text
										found_real_hub = True
									else:
										_LOGGER.debug("*** RETRY STILL RETURNS AUTO-SUBMIT - PROCEEDING WITH FORM v0.0.55 ***")
							
							# Strategy 3: If everything failed, follow the auto-submit as last resort
							if not found_real_hub:
								_LOGGER.debug("*** ALL STRATEGIES FAILED - FOLLOWING AUTO-SUBMIT v0.0.55 ***")
								form_result = await _auto_submit_openid_form(self.session, text, referer=dashboard_url)
								if form_result.executed and form_result.final_text:
									text = form_result.final_text
									_LOGGER.debug(f"*** USING AUTO-SUBMIT RESULT v0.0.55 *** length={len(text)}")
						else:
							# Safe to follow the auto-submit
							_LOGGER.debug("*** AUTO-SUBMIT SAFE - PROCEEDING v0.0.55 ***")
							form_result = await _auto_submit_openid_form(self.session, text, referer=dashboard_url)
							if form_result.executed and form_result.final_text:
								text = form_result.final_text
								_LOGGER.debug(f"*** USING AUTO-SUBMIT FINAL RESPONSE v0.0.55 *** length={len(text)}")
					else:
						_LOGGER.debug("*** NO ACTION URL FOUND IN AUTO-SUBMIT FORM v0.0.55 ***")

				# Check if school selection fields appear on hub (shouldn't happen if credentials were submitted correctly)
				if "IdpListRepeater" in text and ("elever" in text or "kommun" in text):
					school_selection_attempts += 1
					_LOGGER.warning(f"*** UNEXPECTED: SCHOOL SELECTION FIELDS ON HUB v0.0.98 *** attempt {school_selection_attempts}/{max_school_selection_attempts}")
					_LOGGER.warning("*** This suggests credentials were not submitted with all form fields")
					
					if school_selection_attempts > max_school_selection_attempts:
						_LOGGER.error("School selection loop detected — stopping after %d attempts", school_selection_attempts)
						raise InfoMentorAuthError("Unexpected school selection on hub - authentication may have failed")
					# Don't try to select a school - just continue and hope for the best
				else:
					_LOGGER.debug("No school selection fields on hub dashboard (expected)")

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

				# Prefer hub extraction if hub payload is present, even if legacy URLs appear
				if self._has_hub_payload(text):
					_LOGGER.debug("*** HUB PAYLOAD DETECTED - USING HUB JSON EXTRACTION v0.0.70 ***")
					pupil_ids = self._extract_pupil_ids_from_json(text)
				elif "infomentor.se/swedish/production/mentor/" in str(resp.url) or "mentor/" in text:
					_LOGGER.debug("*** DETECTED LEGACY INTERFACE - USING LEGACY EXTRACTION v0.0.70 ***")
					pupil_ids = await self._extract_pupil_ids_legacy(text)
				else:
					_LOGGER.debug("*** USING HUB JSON EXTRACTION v0.0.70 ***")
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
						if _has_openid_form(alt_text):
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
							if self._has_hub_payload(alt_text):
								_LOGGER.debug("*** HUB PAYLOAD DETECTED FROM ALT URL - USING HUB JSON EXTRACTION v0.0.70 ***")
								pupil_ids = self._extract_pupil_ids_from_json(alt_text)
							elif "infomentor.se/swedish/production/mentor/" in str(alt_resp.url) or "mentor/" in alt_text:
								_LOGGER.debug("*** DETECTED LEGACY INTERFACE FROM ALT URL - USING LEGACY EXTRACTION v0.0.70 ***")
								pupil_ids = await self._extract_pupil_ids_legacy(alt_text)
							else:
								_LOGGER.debug("*** USING HUB JSON EXTRACTION FROM ALT URL v0.0.70 ***")
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
			_LOGGER.debug(f"*** TRYING HUB-SPECIFIC EXTRACTION v0.0.53 *** found {len(pupil_ids)} from JSON")
			
			# Look for the comprehensive pupils array in IMHome.home.homeData - PRIORITY extraction
			homedata_pattern = r'IMHome\.home\.homeData\s*=\s*(\{.*?"pupils"\s*:\s*\[.*?\].*?\});'
			homedata_matches = re.findall(homedata_pattern, html_content, re.DOTALL | re.IGNORECASE)
			
			hub_specific_pupil_ids = []  # Use separate list for hub-specific extraction
			hub_specific_pupil_names = {}  # Store names too
			
			for homedata_json in homedata_matches:
				_LOGGER.debug(f"*** FOUND HOMEDATA JSON v0.0.54 *** length={len(homedata_json)}")
				try:
					homedata = json.loads(homedata_json)
					if 'account' in homedata and 'pupils' in homedata['account']:
						pupils_data = homedata['account']['pupils']
						_LOGGER.debug(f"*** FOUND PUPILS ARRAY v0.0.54 *** count={len(pupils_data)}")
						
						for pupil in pupils_data:
							pupil_id = str(pupil.get('id', ''))
							pupil_name = pupil.get('name', '')
							_LOGGER.debug(f"*** PROCESSING PUPIL v0.0.54 *** id={pupil_id} name={pupil_name}")
							if pupil_id and pupil_id not in hub_specific_pupil_ids:
								hub_specific_pupil_ids.append(pupil_id)
								hub_specific_pupil_names[pupil_id] = pupil_name
								_LOGGER.debug(f"*** EXTRACTED PUPIL v0.0.54 *** id={pupil_id} name={pupil_name}")
								
						# If we found pupils via hub-specific method, prioritize them
						if hub_specific_pupil_ids:
							_LOGGER.debug(f"*** USING HUB-SPECIFIC PUPILS v0.0.54 *** count={len(hub_specific_pupil_ids)}")
							pupil_ids = hub_specific_pupil_ids  # Replace any previously found IDs
							
							# Store the pupil names for later use
							self.pupil_names = hub_specific_pupil_names
							_LOGGER.debug(f"*** STORED PUPIL NAMES v0.0.54 *** {self.pupil_names}")
							
							# Skip filtering for hub-specific pupils since they're from authoritative source
							_LOGGER.debug(f"*** RETURNING HUB-SPECIFIC PUPILS WITHOUT FILTERING v0.0.54 *** {pupil_ids}")
							return list(set(pupil_ids))  # Remove duplicates and return immediately
							
				except (json.JSONDecodeError, KeyError) as e:
					_LOGGER.warning(f"*** HOMEDATA PARSING ERROR v0.0.53 *** {e}")
			
			# Fallback: Look for selectedPupilName pattern (single selected pupil)
			if not pupil_ids:
				selected_pupil_pattern = r'selectedPupilName\s*:\s*["\']([^"\']+)["\']'
				selected_matches = re.findall(selected_pupil_pattern, html_content, re.IGNORECASE)
				for pupil_name in selected_matches:
					_LOGGER.debug(f"*** FOUND SELECTED PUPIL NAME v0.0.53 *** {pupil_name}")
					
				# Look for pupil data in the IMHome.init object specifically
				imhome_pattern = r'IMHome\s*=\s*\{[^}]*init\s*:\s*\{([^}]*selectedPupilName[^}]*)\}'
				imhome_matches = re.findall(imhome_pattern, html_content, re.DOTALL | re.IGNORECASE)
				for init_content in imhome_matches:
					_LOGGER.debug(f"*** FOUND IMHOME INIT CONTENT v0.0.53 *** {init_content[:200]}...")
					# Look for any numeric IDs in this context
					id_pattern = r'(\d{6,12})'  # Extended range for longer IDs
					potential_ids = re.findall(id_pattern, init_content)
					for potential_id in potential_ids:
						if potential_id not in pupil_ids and len(potential_id) >= 6:
							pupil_ids.append(potential_id)
							_LOGGER.debug(f"*** EXTRACTED PUPIL ID FROM IMHOME v0.0.53 *** {potential_id}")
			
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
			_LOGGER.debug(f"*** UNIQUE PUPIL IDS v0.0.53 *** {unique_pupil_ids}")
			
			# Filter out any IDs that seem to be parent/user accounts
			filtered_pupil_ids = []
			for pupil_id in unique_pupil_ids:
				is_likely_pupil = self._is_likely_pupil_id(pupil_id, html_content)
				_LOGGER.debug(f"*** FILTERING PUPIL ID v0.0.53 *** {pupil_id} -> likely_pupil={is_likely_pupil}")
				if is_likely_pupil:
					filtered_pupil_ids.append(pupil_id)
					_LOGGER.debug(f"*** KEPT PUPIL ID v0.0.53 *** {pupil_id}")
				else:
					_LOGGER.debug(f"*** FILTERED OUT PUPIL ID v0.0.53 *** {pupil_id}")
			
			_LOGGER.debug(f"*** FINAL FILTERED PUPIL IDS v0.0.53 *** {len(filtered_pupil_ids)} pupils: {filtered_pupil_ids}")
			
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
		_LOGGER.debug("*** EXTRACTING PUPIL IDS FROM LEGACY INTERFACE v0.0.70 ***")

		try:
			# We already have the HTML content from the auto-submit result
			text = html_content

			# Save for debugging
			await _write_text_file_async("/tmp/infomentor_legacy_dashboard.html", text)
			_LOGGER.debug("*** SAVED LEGACY DASHBOARD FOR DEBUG v0.0.70 ***")

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

			_LOGGER.debug(f"*** FOUND LEGACY PUPIL IDS v0.0.70 *** {pupil_ids}")

			if pupil_ids:
				_LOGGER.debug(f"Found {len(pupil_ids)} legacy pupil IDs: {pupil_ids}")
				return pupil_ids

		except Exception as e:
			_LOGGER.error(f"Legacy pupil ID extraction failed: {e}")

		# If no pupil IDs found, try the old method as fallback
		_LOGGER.debug("*** TRYING OLD LEGACY METHOD AS FALLBACK v0.0.70 ***")
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
			# Swallowing cancellation would stall HA shutdown and asyncio timeouts
			raise
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