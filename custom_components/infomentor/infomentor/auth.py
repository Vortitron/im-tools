"""Authentication handler for InfoMentor."""

import logging
import re
from typing import Optional, Dict, Any
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from .exceptions import InfoMentorAuthError, InfoMentorConnectionError

_LOGGER = logging.getLogger(__name__)

HUB_BASE_URL = "https://hub.infomentor.se"
MODERN_BASE_URL = "https://im.infomentor.se"
LEGACY_BASE_URL = "https://infomentor.se/swedish/production/mentor/"

# Headers to mimic browser behaviour
DEFAULT_HEADERS = {
	"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3",
	"Accept-Encoding": "gzip, deflate, br",
	"Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
	"Cache-Control": "no-cache",
	"Connection": "keep-alive",
	"Pragma": "no-cache",
	"Sec-Fetch-Mode": "navigate",
	"Sec-Fetch-Site": "same-origin",
	"Upgrade-Insecure-Requests": "1",
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
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
			
			self.authenticated = True
			_LOGGER.info(f"Successfully authenticated with {len(self.pupil_ids)} pupils")
			return True
			
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
		async with self.session.get(HUB_BASE_URL, headers=headers, allow_redirects=False) as resp:
			if resp.status == 302:
				location = resp.headers.get('Location')
				if location and not location.startswith('http'):
					location = HUB_BASE_URL + location
			else:
				# If no redirect, try to extract from HTML
				text = await resp.text()
				location_match = re.search(r'window\.location\.href\s*=\s*["\']([^"\']+)["\']', text)
				if location_match:
					location = location_match.group(1)
					if not location.startswith('http'):
						location = HUB_BASE_URL + location
				else:
					_LOGGER.error("Could not find redirect location")
					return None
		
		if not location:
			_LOGGER.error("No redirect location found")
			return None
			
		_LOGGER.debug(f"Following redirect to: {location}")
		
		# Follow redirect to get OAuth token
		async with self.session.get(location, headers=headers) as resp:
			text = await resp.text()
			
		# Extract OAuth token using regex pattern from original script
		oauth_match = re.search(r'oauth_token"\s+value="([\w+=/]+)"', text)
		if oauth_match:
			token = oauth_match.group(1)
			_LOGGER.debug(f"Extracted OAuth token: {token[:10]}...")
			return token
		
		_LOGGER.error("Could not extract OAuth token from response")
		return None
	
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
		
		async with self.session.post(
			form_url,
			headers=headers,
			data=urlencode(form_data),
			allow_redirects=True
		) as resp:
			cred_text = await resp.text()
			_LOGGER.debug(f"Credentials response: {resp.status}")
			
			# Look for second OAuth token in the response
			second_oauth_match = re.search(r'oauth_token"\s+value="([\w+=/]+)"', cred_text)
			if second_oauth_match:
				second_oauth_token = second_oauth_match.group(1)
				_LOGGER.debug(f"Found second OAuth token: {second_oauth_token[:10]}...")
				
				# Submit the second OAuth token
				await self._submit_second_oauth_token(second_oauth_token)
			else:
				# Check if credentials were rejected
				if "login_ascx" in cred_text.lower() or "txtnotandanafn" in cred_text.lower():
					raise InfoMentorAuthError("Invalid credentials")
				else:
					_LOGGER.debug("Credentials accepted without second OAuth token")
	
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
			_LOGGER.debug(f"Second OAuth response: {resp.status}")
			
			# Check if we're now authenticated (or at least have partial access)
			if "login_ascx" not in final_text.lower() and "txtnotandanafn" not in final_text.lower():
				_LOGGER.debug("Two-stage OAuth completed successfully")
			else:
				_LOGGER.warning("Two-stage OAuth may not have completed fully")
	
	async def _get_pupil_ids_modern(self) -> list[str]:
		"""Get pupil IDs using the discovered working endpoints."""
		_LOGGER.debug("Getting pupil IDs from Hub endpoints")
		
		# Use the endpoints we know work
		working_endpoints = [
			f"{HUB_BASE_URL}/#/",
			f"{HUB_BASE_URL}/",
		]
		
		for endpoint in working_endpoints:
			try:
				headers = DEFAULT_HEADERS.copy()
				async with self.session.get(endpoint, headers=headers) as resp:
					if resp.status == 200:
						text = await resp.text()
						
						# Use the patterns we know work
						pupil_patterns = [
							r'/Account/PupilSwitcher/SwitchPupil/(\d+)',
							r'SwitchPupil/(\d+)',
							r'"pupilId"\s*:\s*"?(\d+)"?',
							r'"id"\s*:\s*"?(\d+)"?[^}]*"name"',
							r'data-pupil-id=["\'](\d+)["\']',
							r'pupil[^0-9]*(\d{4,8})',
							r'elevid[^0-9]*(\d{4,8})',
						]
						
						pupil_ids = []
						for pattern in pupil_patterns:
							matches = re.findall(pattern, text, re.IGNORECASE)
							# Filter for reasonable pupil ID lengths
							valid_matches = [m for m in matches if 4 <= len(m) <= 8 and m.isdigit()]
							pupil_ids.extend(valid_matches)
						
						# Remove duplicates
						pupil_ids = list(set(pupil_ids))
						
						if pupil_ids:
							_LOGGER.debug(f"Found pupil IDs from {endpoint}: {pupil_ids}")
							return pupil_ids
						
						# Save for debugging if this is the main endpoint
						if endpoint == f"{HUB_BASE_URL}/":
							with open('hub_main_page.html', 'w', encoding='utf-8') as f:
								f.write(text)
							_LOGGER.debug("Saved hub main page for debugging")
			
			except Exception as e:
				_LOGGER.debug(f"Failed to check {endpoint}: {e}")
				continue
		
		# Fallback to legacy approach
		return await self._get_pupil_ids_legacy()
	
	async def _get_pupil_ids_legacy(self) -> list[str]:
		"""Fallback to legacy pupil ID extraction."""
		_LOGGER.debug("Trying legacy pupil ID extraction")
		
		try:
			# Try the legacy default page
			legacy_url = "https://infomentor.se/Swedish/Production/mentor/default.aspx"
			async with self.session.get(legacy_url, headers=DEFAULT_HEADERS) as resp:
				if resp.status == 200:
					text = await resp.text()
					
					# Save for debugging
					with open('legacy_default.html', 'w', encoding='utf-8') as f:
						f.write(text)
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
	
	async def switch_pupil(self, pupil_id: str) -> bool:
		"""Switch to a specific pupil context.
		
		Args:
			pupil_id: ID of pupil to switch to
			
		Returns:
			True if switch successful
		"""
		if pupil_id not in self.pupil_ids:
			raise InfoMentorAuthError(f"Invalid pupil ID: {pupil_id}")
		
		# Try modern switch first
		modern_switch_url = f"{MODERN_BASE_URL}/Account/PupilSwitcher/SwitchPupil/{pupil_id}"
		
		headers = DEFAULT_HEADERS.copy()
		headers["Referer"] = f"{MODERN_BASE_URL}/"
		
		async with self.session.get(modern_switch_url, headers=headers) as resp:
			if resp.status == 200:
				return True
		
		# Fallback to legacy switch
		legacy_switch_url = f"{HUB_BASE_URL}/Account/PupilSwitcher/SwitchPupil/{pupil_id}"
		
		headers["Referer"] = f"{HUB_BASE_URL}/#/"
		
		async with self.session.get(legacy_switch_url, headers=headers) as resp:
			return resp.status == 200 