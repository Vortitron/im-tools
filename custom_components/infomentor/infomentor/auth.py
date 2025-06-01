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
REQUEST_DELAY = 0.8  # 800ms between requests to avoid overwhelming the server

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
			
			if not self.pupil_ids:
				_LOGGER.warning("No pupil IDs found - authentication may have failed or account has no pupils")
				# Try a final verification to see if we're actually authenticated
				await self._verify_authentication_status()
				
				# Even if no pupils found, we might still be authenticated
				# This could happen with parent accounts that haven't been properly configured
				_LOGGER.info("Authentication completed but no pupils found - integration may have limited functionality")
			else:
				_LOGGER.info(f"Successfully authenticated with {len(self.pupil_ids)} pupils")
			
			self.authenticated = True
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
		await asyncio.sleep(REQUEST_DELAY)  # Be respectful to the server
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
		"""Get pupil IDs using the discovered working endpoints."""
		_LOGGER.debug("Getting pupil IDs from Hub endpoints")
		
		# Try the most promising endpoint first (fewer requests)
		primary_endpoint = f"{HUB_BASE_URL}/#/"
		
		try:
			headers = DEFAULT_HEADERS.copy()
			await asyncio.sleep(REQUEST_DELAY)  # Be respectful to the server
			async with self.session.get(primary_endpoint, headers=headers) as resp:
				if resp.status == 200:
					text = await resp.text()
					
					# First try to parse structured JSON data for pupils
					pupil_ids = self._extract_pupil_ids_from_json(text)
					if pupil_ids:
						_LOGGER.debug(f"Found pupil IDs from JSON in {primary_endpoint}: {pupil_ids}")
						return pupil_ids
					
					# Fallback to regex patterns if JSON parsing fails
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
						_LOGGER.debug(f"Found pupil IDs from patterns in {primary_endpoint}: {pupil_ids}")
						return pupil_ids
					
					# Save for debugging
					def _write_debug_file():
						import os
						os.makedirs('debug_output', exist_ok=True)
						with open('debug_output/hub_main_page.html', 'w', encoding='utf-8') as f:
							f.write(text)
					loop = asyncio.get_event_loop()
					await loop.run_in_executor(None, _write_debug_file)
					_LOGGER.debug("Saved hub main page for debugging")
		
		except Exception as e:
			_LOGGER.debug(f"Failed to check {primary_endpoint}: {e}")
		
		# Fallback to legacy approach
		return await self._get_pupil_ids_legacy()
	
	def _extract_pupil_ids_from_json(self, html_content: str) -> list[str]:
		"""Extract pupil IDs from JSON structure in HTML.
		
		Args:
			html_content: HTML content containing JSON data
			
		Returns:
			List of pupil IDs
		"""
		pupil_ids = []
		seen_names = set()  # Track names to avoid duplicates
		
		try:
			# Look for pupil data in JSON format within script tags or JavaScript variables
			# Pattern to find arrays of pupil objects
			json_patterns = [
				r'"pupils"\s*:\s*(\[.*?\])',
				r'"pupils"\s*:\s*(\[[\s\S]*?\])',
				r'"children"\s*:\s*(\[.*?\])',
				r'"students"\s*:\s*(\[.*?\])',
				r'pupils\s*=\s*(\[.*?\]);',
				r'children\s*=\s*(\[.*?\]);',
			]
			
			for pattern in json_patterns:
				matches = re.findall(pattern, html_content, re.IGNORECASE | re.DOTALL)
				for match in matches:
					try:
						pupils_data = json.loads(match)
						if isinstance(pupils_data, list):
							for pupil in pupils_data:
								if isinstance(pupil, dict):
									# Look for pupil ID in various possible fields
									pupil_id = None
									for id_field in ['id', 'pupilId', 'studentId', 'hybridMappingId']:
										if id_field in pupil:
											# Extract numeric ID from hybridMappingId if present
											value = str(pupil[id_field])
											if id_field == 'hybridMappingId':
												# Extract the numeric part from format like "17637|2104025925|NEMANDI_SKOLI"
												parts = value.split('|')
												if len(parts) >= 2 and parts[1].isdigit():
													pupil_id = parts[1]
												elif len(parts) >= 1 and parts[0].isdigit():
													pupil_id = parts[0]
											elif value.isdigit() and 4 <= len(value) <= 10:
												pupil_id = value
											break
									
									if pupil_id:
										# Check if this is actually a child, not the parent
										name = pupil.get('name', '')
										user_role = pupil.get('role', pupil.get('userRole', ''))
										
										# Skip if this appears to be the parent account
										if user_role in ['parent', 'guardian', 'förälder', 'vårdnadshavare']:
											_LOGGER.debug(f"Skipping parent account: {name} (ID: {pupil_id})")
											continue
										
										# Skip if the name matches common parent name patterns
										if any(indicator in name.lower() for indicator in ['andrew', 'förälder', 'parent']):
											_LOGGER.debug(f"Skipping potential parent name: {name} (ID: {pupil_id})")
											continue
										
										# Skip duplicates based on name
										if name in seen_names:
											_LOGGER.debug(f"Skipping duplicate pupil name: {name} (ID: {pupil_id})")
											continue
										
										pupil_ids.append(pupil_id)
										seen_names.add(name)
										_LOGGER.debug(f"Found pupil from JSON: {name} (ID: {pupil_id})")
					except (json.JSONDecodeError, KeyError, ValueError) as e:
						_LOGGER.debug(f"Failed to parse pupils JSON: {e}")
						continue
			
			# Also look for individual pupil objects embedded in larger JSON structures
			# Look for switchPupilUrl patterns which are reliable indicators
			switch_pattern = r'"switchPupilUrl"\s*:\s*"[^"]*SwitchPupil/(\d+)"[^}]*"name"\s*:\s*"([^"]+)"'
			matches = re.findall(switch_pattern, html_content, re.IGNORECASE)
			
			for pupil_id, name in matches:
				# Additional filtering to exclude parent accounts
				if any(indicator in name.lower() for indicator in ['andrew', 'förälder', 'parent']):
					_LOGGER.debug(f"Skipping potential parent in switch pattern: {name} (ID: {pupil_id})")
					continue
				
				# Skip duplicates based on name
				if name in seen_names:
					_LOGGER.debug(f"Skipping duplicate pupil name in switch pattern: {name} (ID: {pupil_id})")
					continue
				
				if pupil_id not in pupil_ids:
					pupil_ids.append(pupil_id)
					seen_names.add(name)
					_LOGGER.debug(f"Found pupil from switch pattern: {name} (ID: {pupil_id})")
			
		except Exception as e:
			_LOGGER.debug(f"Error in JSON pupil extraction: {e}")
		
		# Remove duplicates and return
		return list(set(pupil_ids))
	
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