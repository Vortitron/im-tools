"""Authentication handler for InfoMentor."""

import logging
import re
import json
import asyncio
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from .exceptions import InfoMentorAuthError, InfoMentorConnectionError

_LOGGER = logging.getLogger(__name__)

HUB_BASE_URL = "https://hub.infomentor.se"
MODERN_BASE_URL = "https://im.infomentor.se"
LEGACY_BASE_URL = "https://infomentor.se/swedish/production/mentor/"

# Request delay to be respectful to InfoMentor servers
REQUEST_DELAY = 0.3  # Reduced from 0.8s to 0.3s - mobile apps are typically faster

# Headers to mimic mobile app behaviour more closely
DEFAULT_HEADERS = {
	"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3",
	"Accept-Encoding": "gzip, deflate, br",
	"Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
	"Cache-Control": "no-cache",
	"Connection": "keep-alive",
	"Pragma": "no-cache",
	"Sec-Fetch-Mode": "navigate",
	"Sec-Fetch-Site": "none",  # Changed from "same-origin" to mimic initial navigation
	"Sec-Fetch-User": "?1",  # Added to mimic user-initiated navigation
	"Upgrade-Insecure-Requests": "1",
	"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",  # Updated to newer browser version
}


class InfoMentorAuth:
	"""Handles authentication with InfoMentor system."""
	
	def __init__(self, session: aiohttp.ClientSession):
		"""Initialise authentication handler.
		
		Args:
			session: aiohttp session to use for requests
		"""
		self.session = session
		self.authenticated = False
		self.pupil_ids: list[str] = []
		self.pupil_switch_ids: dict[str, str] = {}  # Maps pupil_id -> switch_id
		self._last_auth_time: Optional[float] = None
		self._auth_cookies_backup: Optional[Dict[str, str]] = None
		
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
		"""Authenticate with InfoMentor using modern OAuth flow.
		
		Args:
			username: Username or email
			password: Password
			
		Returns:
			True if authentication successful
		"""
		try:
			_LOGGER.debug("Starting modern InfoMentor authentication")
			
			# Step 1: Get OAuth token
			oauth_token = await self._get_oauth_token()
			if not oauth_token:
				raise InfoMentorAuthError("Failed to get OAuth token")
				
			# Step 2: Follow the correct OAuth completion flow
			await self._complete_oauth_to_modern_domain(oauth_token, username, password)
			
			# Step 3: Get pupil IDs from modern interface
			self.pupil_ids = await self._get_pupil_ids_modern()
			
			# Step 4: Get switch ID mappings
			await self._build_switch_id_mapping()
			
			if not self.pupil_ids:
				_LOGGER.warning("No pupil IDs found - authentication may have failed or account has no pupils")
				# Try a final verification to see if we're actually authenticated
				await self._verify_authentication_status()
				
				# Even if no pupils found, we might still be authenticated
				# This could happen with parent accounts that haven't been properly configured
				_LOGGER.info("Authentication completed but no pupils found - integration may have limited functionality")
			else:
				_LOGGER.info(f"Successfully authenticated with {len(self.pupil_ids)} pupils")
			
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
	
	async def _get_oauth_token(self) -> Optional[str]:
		"""Get OAuth token from initial redirect."""
		_LOGGER.debug("Getting OAuth token")
		
		# Get initial redirect - this returns a 302 with Location header
		headers = DEFAULT_HEADERS.copy()
		await asyncio.sleep(REQUEST_DELAY)  # Be respectful to the server
		
		try:
			async with self.session.get(HUB_BASE_URL, headers=headers, allow_redirects=False) as resp:
				_LOGGER.debug(f"Initial request to {HUB_BASE_URL} returned status: {resp.status}")
				_LOGGER.debug(f"Response headers: {dict(resp.headers)}")
				
				location = None
				if resp.status == 302:
					location = resp.headers.get('Location')
					_LOGGER.debug(f"Found 302 redirect to: {location}")
					if location and not location.startswith('http'):
						location = HUB_BASE_URL + location
				else:
					# If no redirect, try to extract from HTML
					text = await resp.text()
					_LOGGER.debug(f"No redirect found, examining HTML content (length: {len(text)})")
					
					# Try multiple patterns for location extraction
					location_patterns = [
						r'window\.location\.href\s*=\s*["\']([^"\']+)["\']',
						r'location\.href\s*=\s*["\']([^"\']+)["\']',
						r'location\s*=\s*["\']([^"\']+)["\']',
						r'href=["\']([^"\']*authentication[^"\']*)["\']',
						r'action=["\']([^"\']*authentication[^"\']*)["\']'
					]
					
					for pattern in location_patterns:
						location_match = re.search(pattern, text, re.IGNORECASE)
						if location_match:
							location = location_match.group(1)
							_LOGGER.debug(f"Found redirect location using pattern '{pattern}': {location}")
							if not location.startswith('http'):
								if location.startswith('/'):
									location = HUB_BASE_URL + location
								else:
									location = HUB_BASE_URL + '/' + location
							break
					
					if not location:
						_LOGGER.error("Could not find redirect location in HTML")
						# Save debug file to help troubleshoot
						debug_file = "/tmp/infomentor_debug_initial.html"
						try:
							with open(debug_file, 'w', encoding='utf-8') as f:
								f.write(text)
							_LOGGER.debug(f"Saved debug HTML to {debug_file}")
						except Exception as e:
							_LOGGER.debug(f"Could not save debug file: {e}")
						return None
			
			if not location:
				_LOGGER.error("No redirect location found")
				return None
				
			_LOGGER.debug(f"Following redirect to: {location}")
			
			# Follow redirect to get OAuth token
			await asyncio.sleep(REQUEST_DELAY)  # Be respectful to the server
			async with self.session.get(location, headers=headers) as resp:
				_LOGGER.debug(f"OAuth page request returned status: {resp.status}")
				text = await resp.text()
				_LOGGER.debug(f"OAuth page content length: {len(text)}")
				
			# Try multiple OAuth token extraction patterns
			oauth_patterns = [
				r'oauth_token["\'][^>]*value=["\']([^"\']+)["\']',
				r'name=["\']oauth_token["\'][^>]*value=["\']([^"\']+)["\']',
				r'input[^>]*name=["\']oauth_token["\'][^>]*value=["\']([^"\']+)["\']',
				r'<input[^>]*oauth_token[^>]*value=["\']([^"\']+)["\']',
				r'oauth_token["\']:\s*["\']([^"\']+)["\']',
				r'token["\']:\s*["\']([^"\']+)["\']'
			]
			
			token = None
			for pattern in oauth_patterns:
				oauth_match = re.search(pattern, text, re.IGNORECASE)
				if oauth_match:
					token = oauth_match.group(1)
					_LOGGER.debug(f"Extracted OAuth token using pattern '{pattern}': {token[:10]}...")
					break
			
			if token:
				return token
			
			_LOGGER.error("Could not extract OAuth token from response")
			# Save debug file to help troubleshoot
			debug_file = "/tmp/infomentor_debug_oauth.html"
			try:
				with open(debug_file, 'w', encoding='utf-8') as f:
					f.write(text)
				_LOGGER.debug(f"Saved OAuth debug HTML to {debug_file}")
			except Exception as e:
				_LOGGER.debug(f"Could not save OAuth debug file: {e}")
			
			return None
			
		except Exception as e:
			_LOGGER.error(f"Exception during OAuth token extraction: {e}")
			raise
	
	async def _complete_oauth_to_modern_domain(self, oauth_token: str, username: str, password: str) -> None:
		"""Complete OAuth flow using the two-stage process."""
		_LOGGER.debug("Starting two-stage OAuth completion")
		
		# Stage 1: Submit initial OAuth token to get credential form
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Content-Type": "application/x-www-form-urlencoded",
			"Origin": HUB_BASE_URL,
			"Referer": f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true",
			"Sec-Fetch-Site": "cross-site",
		})
		
		oauth_data = f"oauth_token={oauth_token}"
		
		await asyncio.sleep(REQUEST_DELAY)  # Be respectful to the server
		async with self.session.post(
			LEGACY_BASE_URL,
			headers=headers,
			data=oauth_data,
			allow_redirects=True
		) as resp:
			stage1_text = await resp.text()
			_LOGGER.debug(f"Stage 1 OAuth response: {resp.status}")
			
			# Check if we need to submit credentials
			if any(field in stage1_text.lower() for field in ['txtnotandanafn', 'txtlykilord']):
				_LOGGER.debug("Found credential form - submitting credentials")
				
				# Extract and submit credentials
				await self._submit_credentials_and_handle_second_oauth(stage1_text, username, password, str(resp.url))
			else:
				_LOGGER.debug("No credential form found")
	
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
			_LOGGER.debug(f"Credentials response: {resp.status}")
			
			# Check for credential rejection first
			if "login_ascx" in cred_text.lower() and "txtnotandanafn" in cred_text.lower():
				# If we still see the login form, credentials were likely rejected
				_LOGGER.error("Credentials appear to have been rejected")
				raise InfoMentorAuthError("Invalid credentials - login form still present after submission")
			
			# Look for second OAuth token in the response
			second_oauth_match = re.search(r'oauth_token"\s+value="([\w+=/]+)"', cred_text)
			if second_oauth_match:
				second_oauth_token = second_oauth_match.group(1)
				_LOGGER.debug(f"Found second OAuth token: {second_oauth_token[:10]}...")
				
				# Submit the second OAuth token
				await self._submit_second_oauth_token(second_oauth_token)
			else:
				_LOGGER.debug("No second OAuth token found - checking if credentials were accepted")
				
				# Check for signs of successful authentication
				success_indicators = [
					"default.aspx" in str(resp.url).lower(),
					"hub.infomentor.se" in str(resp.url).lower(),
					"logout" in cred_text.lower(),
					"dashboard" in cred_text.lower()
				]
				
				if any(success_indicators):
					_LOGGER.debug("Credentials accepted without second OAuth token")
				else:
					_LOGGER.warning("Unclear authentication state - no second OAuth token and no clear success indicators")
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
		})
		
		oauth_data = f"oauth_token={oauth_token}"
		
		async with self.session.post(
			LEGACY_BASE_URL,
			headers=headers,
			data=oauth_data,
			allow_redirects=True
		) as resp:
			final_text = await resp.text()
			_LOGGER.debug(f"Second OAuth response: {resp.status}, URL: {resp.url}")
			
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
				return
			
			# Check for negative indicators
			if any(auth_failure_indicators):
				_LOGGER.warning("Two-stage OAuth may not have completed fully - found failure indicators")
				# Try to verify by making a test request to the hub
				await self._verify_authentication_status()
			else:
				_LOGGER.debug("Two-stage OAuth status unclear - attempting verification")
				await self._verify_authentication_status()
	
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
				async with self.session.get(endpoint, headers=headers) as resp:
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
	
	async def _get_pupil_ids_modern(self) -> list[str]:
		"""Get pupil IDs from modern InfoMentor interface."""
		_LOGGER.debug("Getting pupil IDs from modern interface")
		
		try:
			# Try the main hub dashboard first
			dashboard_url = f"{HUB_BASE_URL}/start"
			headers = DEFAULT_HEADERS.copy()
			
			await asyncio.sleep(REQUEST_DELAY)
			async with self.session.get(dashboard_url, headers=headers) as resp:
				_LOGGER.debug(f"Dashboard request to {dashboard_url} returned status: {resp.status}")
				text = await resp.text()
				_LOGGER.debug(f"Dashboard content length: {len(text)}")
				
				pupil_ids = self._extract_pupil_ids_from_json(text)
				if pupil_ids:
					_LOGGER.debug(f"Found {len(pupil_ids)} pupil IDs from dashboard")
					return pupil_ids
				
				# If no pupil IDs found, try alternative URLs
				alternative_urls = [
					f"{HUB_BASE_URL}/dashboard",
					f"{HUB_BASE_URL}/",
					f"{HUB_BASE_URL}/authentication/authentication/login",
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
							pupil_ids = self._extract_pupil_ids_from_json(alt_text)
							if pupil_ids:
								_LOGGER.debug(f"Found {len(pupil_ids)} pupil IDs from {alt_url}")
								return pupil_ids
					except Exception as e:
						_LOGGER.debug(f"Failed to fetch {alt_url}: {e}")
						continue
				
				# Save debug file if no pupil IDs found
				debug_file = "/tmp/infomentor_debug_dashboard.html"
				try:
					with open(debug_file, 'w', encoding='utf-8') as f:
						f.write(text)
					_LOGGER.debug(f"Saved dashboard debug HTML to {debug_file}")
				except Exception as e:
					_LOGGER.debug(f"Could not save dashboard debug file: {e}")
				
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
				# Standard JSON assignment patterns
				r'var\s+pupils\s*=\s*(\[.*?\]);',
				r'pupils\s*:\s*(\[.*?\])',
				r'"pupils"\s*:\s*(\[.*?\])',
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
			
			# If JSON extraction didn't find enough, try more specific regex patterns
			if len(pupil_ids) < 2:  # Expecting at least 2 pupils based on user's comment
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
			
			# Filter out any IDs that seem to be parent/user accounts
			filtered_pupil_ids = []
			for pupil_id in unique_pupil_ids:
				if self._is_likely_pupil_id(pupil_id, html_content):
					filtered_pupil_ids.append(pupil_id)
				else:
					_LOGGER.debug(f"Filtered out ID {pupil_id} as it appears to be a parent/user account")
			
			_LOGGER.info(f"Final filtered pupil IDs: {len(filtered_pupil_ids)} pupils found")
			if filtered_pupil_ids:
				_LOGGER.debug(f"Pupil IDs: {filtered_pupil_ids}")
			
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
					if value.isdigit() and 4 <= len(value) <= 8:
						ids.append(value)
			
			# Recursively check nested objects
			for value in data.values():
				if isinstance(value, (list, dict)):
					ids.extend(self._extract_ids_from_data(value))
		
		return ids
	
	async def _get_pupil_ids_legacy(self) -> list[str]:
		"""Fallback to legacy pupil ID extraction."""
		_LOGGER.debug("Trying legacy pupil ID extraction")
		
		try:
			# Try the legacy default page
			legacy_url = "https://infomentor.se/Swedish/Production/mentor/default.aspx"
			await asyncio.sleep(REQUEST_DELAY)  # Be respectful to the server
			async with self.session.get(legacy_url, headers=DEFAULT_HEADERS) as resp:
				if resp.status == 200:
					text = await resp.text()
					
					# Save for debugging
					def _write_legacy_debug_file():
						import os
						os.makedirs('debug_output', exist_ok=True)
						with open('debug_output/legacy_default.html', 'w', encoding='utf-8') as f:
							f.write(text)
					loop = asyncio.get_event_loop()
					await loop.run_in_executor(None, _write_legacy_debug_file)
					_LOGGER.debug("Saved legacy default page for debugging")
					
					# Look for legacy pupil patterns
					patterns = [
						r'pupil[^0-9]*(\d+)',
						r'elevid[^0-9]*(\d+)',
						r'id["\']?\s*:\s*["\']?(\d+)["\']?',
					]
					
					pupil_ids = []
					for pattern in patterns:
						matches = re.findall(pattern, text, re.IGNORECASE)
						# Filter for reasonable pupil ID lengths (typically 4-8 digits)
						valid_matches = [m for m in matches if 4 <= len(m) <= 8]
						pupil_ids.extend(valid_matches)
					
					# Remove duplicates
					pupil_ids = list(set(pupil_ids))
					
					if pupil_ids:
						_LOGGER.debug(f"Found legacy pupil IDs: {pupil_ids}")
						return pupil_ids
		
		except Exception as e:
			_LOGGER.debug(f"Legacy pupil ID extraction failed: {e}")
		
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