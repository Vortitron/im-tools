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
		"""Authenticate with InfoMentor.
		
		Args:
			username: Username or email
			password: Password
			
		Returns:
			True if authentication successful
			
		Raises:
			InfoMentorAuthError: If authentication fails
			InfoMentorConnectionError: If connection fails
		"""
		try:
			_LOGGER.debug("Starting InfoMentor authentication")
			
			# Step 1: Get initial redirect and oauth token
			oauth_token = await self._get_oauth_token()
			if not oauth_token:
				raise InfoMentorAuthError("Failed to get OAuth token")
				
			# Step 2: Initial login page to set cookies
			await self._initial_login_page(oauth_token)
			
			# Step 3: Send credentials
			await self._send_credentials(username, password)
			
			# Step 4: Handle PIN page (don't activate)
			await self._handle_pin_page()
			
			# Step 5: Complete OAuth flow
			callback_url = await self._get_callback_url(oauth_token)
			if not callback_url:
				raise InfoMentorAuthError("Failed to get callback URL")
				
			# Step 6: Execute callback to complete auth
			await self._execute_callback(callback_url)
			
			# Step 7: Get pupil IDs
			self.pupil_ids = await self._get_pupil_ids()
			
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
	
	async def _initial_login_page(self, oauth_token: str) -> None:
		"""Set initial cookies with OAuth token."""
		_LOGGER.debug("Setting initial cookies")
		
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Content-Type": "application/x-www-form-urlencoded",
			"Origin": HUB_BASE_URL,
			"Referer": f"{HUB_BASE_URL}/Authentication/Authentication/Login?ReturnUrl=%2F",
		})
		
		data = f"oauth_token={oauth_token}"
		
		async with self.session.post(
			LEGACY_BASE_URL,
			headers=headers,
			data=data
		) as resp:
			pass  # Just need to set cookies
	
	async def _send_credentials(self, username: str, password: str) -> None:
		"""Send login credentials."""
		_LOGGER.debug("Sending credentials")
		
		# First, get the login page to extract current form data
		async with self.session.get(LEGACY_BASE_URL, headers=DEFAULT_HEADERS) as resp:
			login_page_content = await resp.text()
		
		# Extract form data dynamically
		auth_data = self._build_auth_payload_dynamic(username, password, login_page_content)
		
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Content-Type": "application/x-www-form-urlencoded",
			"Origin": "https://infomentor.se",
			"Sec-Fetch-Mode": "navigate",
			"Sec-Fetch-User": "?1",
		})
		
		async with self.session.post(
			LEGACY_BASE_URL,
			headers=headers,
			data=auth_data
		) as resp:
			text = await resp.text()
			_LOGGER.debug(f"Credentials response status: {resp.status}")
			if "login_ascx" in text.lower():
				raise InfoMentorAuthError("Invalid credentials")
	
	def _build_auth_payload_dynamic(self, username: str, password: str, login_page_content: str) -> str:
		"""Build authentication payload by extracting current form data."""
		import re
		
		# Extract ViewState
		viewstate_match = re.search(r'__VIEWSTATE" value="([^"]+)"', login_page_content)
		viewstate = viewstate_match.group(1) if viewstate_match else ""
		
		# Extract ViewStateGenerator
		viewstate_gen_match = re.search(r'__VIEWSTATEGENERATOR" value="([^"]+)"', login_page_content)
		viewstate_gen = viewstate_gen_match.group(1) if viewstate_gen_match else ""
		
		# Extract EventValidation
		event_validation_match = re.search(r'__EVENTVALIDATION" value="([^"]+)"', login_page_content)
		event_validation = event_validation_match.group(1) if event_validation_match else ""
		
		_LOGGER.debug(f"Extracted ViewState: {viewstate[:50]}...")
		_LOGGER.debug(f"Extracted ViewStateGenerator: {viewstate_gen}")
		_LOGGER.debug(f"Extracted EventValidation: {event_validation[:50]}...")
		
		# Build the form data
		form_data = {
			"__EVENTTARGET": "login_ascx$btnLogin",
			"__EVENTARGUMENT": "",
			"__VIEWSTATE": viewstate,
			"__VIEWSTATEGENERATOR": viewstate_gen,
			"__EVENTVALIDATION": event_validation,
			"login_ascx$txtNotandanafn": username,
			"login_ascx$txtLykilord": password
		}
		
		# Convert to URL-encoded string
		from urllib.parse import urlencode
		return urlencode(form_data)
	
	def _build_auth_payload(self, username: str, password: str) -> str:
		"""Build authentication payload (fallback method)."""
		# This is the old hardcoded version - keeping as fallback
		base_payload = """__EVENTARGUMENT=&__EVENTTARGET=login_ascx%24btnLogin&__EVENTVALIDATION=%2FwEdAEQ%2Bz3JMUfGRFu9qBveDzs6%2Fltz7opyNJXSrcI9jTx1%2BlwVPpHgdinivleVzI89iVA421KgxS1EZmzzNKriRE1ZD5W7aGh6Y0r6%2FFUu67mirBq3yx63sSrIX0x%2FjZ7J4OfARNaGKLfHqE%2Bnr0wUXQWVY8f20RecOsx8Ea4JJJuOFYHvCF7uYJxJOUFc6gyKVswRw%2Byt1NirfMAm31pxAhxHGS%2F9QI76%2BsIQawaeJQ63oOysmDUmxgEfuzVxc80DL1LLyV8KnKa2CgAbd7vUpKCpsQAs9PCoWr0nBs7O0tCfgCz4jtdc%2FaoCiBNFpzfT7UFKbqvRX%2FoWWDKGOyca3asAtEMXvkaE9t7XfU6Dm9gujyaGp6EczgCbLKS41BL1VTDVtKGpEXYEaeKEKW3URWhChumJ8GK2PdRW6SS21Kd%2FhVq%2B7ZmBkZc1KVC3%2BMbbHB8liPLefVqMSgOu4d4fVA6te6eBMP8H1NXLY1t3ksxu4ab51TeocFgNagYR4%2BGqi3HK3P01HF3011rcuBclg%2BCLgfWGRQ%2FxVK690tVai6S2qrlwTaMOgYb5oqNqUUAjVJJcIBAP5Az048JxYHwycBrgy9zKTO6zAVHjECLcpDfZLARROL8HM%2FkCr3SY6qKFWgPKW%2FfI2fcBs42fRZi1d%2FmDe9d3%2F%2FJuldNGZpVggF5h69rlni7QczAJWlMEbHnat8KXxPoHt0gPAOGzbjLO84vmDywAXGCcrgsrfGDUznhWlmjZrn2UrjNPqvkoPczkGzaTFTgxNvT8HaZqyA4dYZs9%2FikakJqqOepQUGBJG4ASwqxMMXEA4TSo7OMrIDZPJvxo%2FyEPGONbv9d0iK7gJgK2boNT1x8QJFS5Tv0wGouJOR0fX7z83WzNLb5XbdcFWzm44%2Fdjt83vTBRems%2BSGoAL329I3%2FD4Z6Ox7efR2srKP0weqg8ESNN%2BL%2BfpQHqqVKMrkZEGrJ%2Fd85ueo1XEjaPJnlSIEyLDWkA5v3JStwIHJUmyCUoFFmrgD9zlm44ZogPeLxXTerunmF9ZgPkupKrYyETw2KvoEIFmiAAieJJTOW4O2rebaORVjR2K6F9kjkl1KADD3EtnjhMxYxN9SBz7jaO%2F4%2F6Xrvt555gJVGuWN70DQD0Cvo%2BUFoL0OjSzHsBZBP6hGc8JO6U%2FZMOvONwCCB90JLTvrRrrbsJKa06B0beZUsn05Z9ig5YzS72CU%2FvEgR6MHdNi9%2FZilDVRmCZYbwMBWL%2BxrUq8EBkp63P00lI1oWJblFJam4e201idzwOdOGrAGZTcUPNTZcUlGePx2uth5SEQ9ZzqctN20n0667GYWGKTOPKHdkgR%2BJI1jum9ckfY%2F4OWQGymDglX3H0Y3vZmrIFFF6WgyHHmc7NnFesmmf4pmQpWDHwgRfNatKI1dcH8032t6Bko%2FhXDLUpgYtn8QZMJfHDvmvK6qf3tygb3J30Ommmbo3Nnvv3GDoDHl33h0&__VIEWSTATE=%2FwEPDwUJOTgxMjQwMjYxD2QWAmYPZBYCAgEPZBYCZg9kFggCAQ9kFgQCAQ9kFhBmDw8WAh4EVGV4dAUITG9nZ2EgaW5kZAIBDw8WAh4HVmlzaWJsZWhkZAICDw8WAh8BaGRkAgQPDxYEHgxFcnJvck1lc3NhZ2UFFUFudsOkbmRhcm5hbW4gc2FrbmFzIR4HRGlzcGxheQsqKlN5c3RlbS5XZWIuVUkuV2ViQ29udHJvbHMuVmFsaWRhdG9yRGlzcGxheQJkZAIFDw8WBB8CBRFMw7ZzZW5vcmQgZmF0dGFzIR8DCysEAmRkAgYPDxYCHwAFDUFudsOkbmRhcm5hbW5kZAIJDw8WAh8ABQlMw7ZzZW5vcmRkZAIMDw8WAh8BZ2QWAgIBDw8WAh8ABRFHbMO2bXQgbMO2c2Vub3JkP2RkAgMPFgIfAWgWBAICDw8WAh8CBQpQSU4ga3LDpHZzZGQCAw8PFgIfAAURQW5nZSBkaW4gUElOLWtvZDpkZAICD2QWAgIDDw8WAh8BZ2QWBAIBDw8WAh8ABSJBbGxhIGVsZXZlciA8YnIgLz4gc2thIG7DpSBtw6VsZW4hZGQCBQ8WBB4EaHJlZgUYaHR0cDovL3d3dy5pbmZvbWVudG9yLnNlHglpbm5lcmh0bWwFEXd3dy5pbmZvbWVudG9yLnNlZAIDDxYCHwFoZAIEDw8WAh8BZ2QWAgIBDxYCHgtfIUl0ZW1Db3VudAIgFkBmD2QWBAIFDw8WBB4ISW1hZ2VVcmwFFy4uL0lkcExvZ28uYXNweD9maWxlPTM0HwFnZGQCBw8PFgIfAAUMQmp1dnMga29tbXVuZGQCAQ9kFgQCBQ8PFgQfBwUXLi4vSWRwTG9nby5hc3B4P2ZpbGU9MzYfAWdkZAIHDw8WAh8ABSJFa2Vyw7Yga29tbXVuLCBwZXJzb25hbCBvY2ggZWxldmVyZGQCAg9kFgQCBQ8PFgQfBwUXLi4vSWRwTG9nby5hc3B4P2ZpbGU9MzUfAWdkZAIHDw8WAh8ABR5Fa2Vyw7Yga29tbXVuLCB2w6VyZG5hZHNoYXZhcmVkZAIDD2QWBAIFDw8WBB8HBRcuLi9JZHBMb2dvLmFzcHg%2FZmlsZT0zNx8BZ2RkAgcPDxYCHwAFEUZpbGlwc3RhZHMga29tbXVuZGQCBA9kFgICBw8PFgIfAAUNR25lc3RhIGtvbW11bmRkAgUPZBYCAgcPDxYCHwAFJUhhcGFyYW5kYSBrb21tdW4sIHBlcnNvbmFsIG9jaCBlbGV2ZXJkZAIGD2QWAgIHDw8WAh8ABQ1Ib2ZvcnMga29tbXVuZGQCBw9kFgQCBQ8PFgQfBwUXLi4vSWRwTG9nby5hc3B4P2ZpbGU9NDAfAWdkZAIHDw8WAh8ABQ5Ow7bDtnJzIGtvbW11bmRkAggPZBYEAgUPDxYEHwcFFy4uL0lkcExvZ28uYXNweD9maWxlPTQxHwFnZGQCBw8PFgIfAAUOS3Jva29tcyBrb21tdW5kZAIJD2QWAgIHDw8WAh8ABSFLdW1sYSBrb21tdW4sIHBlcnNvbmFsIG9jaCBlbGV2ZXJkZAIKD2QWAgIHDw8WAh8ABR1LdW1sYSBrb21tdW4sIHbDpXJkbmFkc2hhdmFyZWRkAgsPZBYCAgcPDxYCHwAFGUt1bmdzw7ZyIGtvbW11biwgcGVyc29uYWwgb2NoIGVsZXZlcmRkAg0PZBYCAgcPDxYCHwAFJUxla2ViZXJncyBrb21tdW4sIHBlcnNvbmFsIG9jaCBlbGV2ZXJkZAIOD2QWBAIFDw8WBB8HBRcuLi9JZHBMb2dvLmFzcHg%2FZmlsZT00Nx8BZ2RkAgcPDxYCHwAFDExvbW1hIGtvbW11bmRkAg8PZBYEAgUPDxYEHwcFFy4uL0lkcExvZ28uYXNweD9maWxlPTQ4HwFnZGQCBw8PFgIfAAUPTHlja3NlbGUga29tbXVuZGQCEA9kFgICBw8PFgIfAAUPTXVua2ZvcnMga29tbXVuZGQCEQ9kFgICBw8PFgIfAAUhTmFja2Ega29tbXVuLCBwZXJzb25hbCBvY2ggZWxldmVyZGQCEg9kFgICBw8PFgIfAAUdTmFja2Ega29tbXVuLCB2w6VyZG5hZHNoYXZhcmVkZAITD2QWBAIFDw8WBB8HBRcuLi9JZHBMb2dvLmFzcHg%2FZmlsZT01Mh8BZ2RkAgcPDxYCHwAFEk9sb2ZzdHLDtm1zIGtvbW11bmRkAhQPZBYEAgUPDxYEHwcFFy4uL0lkcExvZ28uYXNweD9maWxlPTU2HwFnZGQCBw8PFgIfAAUuU2tlbGxlZnRlw6Uga29tbXVuLCBlbGV2ZXIgb2NoIHbDpXJkbmFkc2hhdmFyZWRkAhUPZBYEAgUPDxYEHwcFFy4uL0lkcExvZ28uYXNweD9maWxlPTUzHwFnZGQCBw8PFgIfAAUpU21lZGplYmFja2VucyBrb21tdW4sIHBlcnNvbmFsIG9jaCBlbGV2ZXJkZAIWD2QWBAIFDw8WBB8HBRcuLi9JZHBMb2dvLmFzcHg%2FZmlsZT02Nh8BZ2RkAgcPDxYCHwAFJVNtZWRqZWJhY2tlbnMga29tbXVuLCB2w6VyZG5hZHNoYXZhcmVkZAIXD2QWAgIHDw8WAh8ABSZTb2xsZW50dW5hIGtvbW11biwgcGVyc29uYWwgb2NoIGVsZXZlcmRkAhgPZBYCAgcPDxYCHwAFIlNvbGxlbnR1bmEga29tbXVuLCB2w6VyZG5hZHNoYXZhcmVkZAIZD2QWAgIHDw8WAh8ABQpTb2xuYSBzdGFkZGQCGg9kFgQCBQ8PFgQfBwUXLi4vSWRwTG9nby5hc3B4P2ZpbGU9NjAfAWdkZAIHDw8WAh8ABRpTdW5kYnliZXJncyBzdGFkLCBwZXJzb25hbGRkAhsPZBYEAgUPDxYEHwcFFy4uL0lkcExvZ28uYXNweD9maWxlPTYxHwFnZGQCBw8PFgIfAAUhU3VuZGJ5YmVyZ3Mgc3RhZCwgdsOlcmRuYWRzaGF2YXJlZGQCHA9kFgQCBQ8PFgQfBwUXLi4vSWRwTG9nby5hc3B4P2ZpbGU9NjIfAWdkZAIHDw8WAh8ABQxUaWJybyBrb21tdW5kZAIdD2QWBAIFDw8WBB8HBRcuLi9JZHBMb2dvLmFzcHg%2FZmlsZT02Mx8BZ2RkAgcPDxYCHwAFDlRyYW5lbW8ga29tbXVuZGQCHg9kFgQCBQ8PFgQfBwUXLi4vSWRwTG9nby5hc3B4P2ZpbGU9NjQfAWdkZAIHDw8WAh8ABRJVbHJpY2VoYW1ucyBrb21tdW5kZAIfD2QWBAIFDx8HBRcuLi9JZHBMb2dvLmFzcHg%2FZmlsZT02NR8BZ2RkAgcPDxYCHwAFE8OWcmtlbGxqdW5nYSBrb21tdW5kZGR%2Bu6KV4m8RysmyzoX%2FHiC4q%2FqiNQ%3D%3D&__VIEWSTATEGENERATOR=F357C404"""
		
		# Replace username and password placeholders
		return base_payload + f"&login_ascx%24txtLykilord={password}&login_ascx%24txtNotandanafn={username}"
	
	async def _handle_pin_page(self) -> None:
		"""Handle PIN activation page by declining activation."""
		_LOGGER.debug("Handling PIN page")
		
		# Get the PIN enable page
		enable_pin_url = "https://infomentor.se/Swedish/Production/mentor/Oryggi/PinLogin/EnablePin.aspx"
		
		headers = DEFAULT_HEADERS.copy()
		headers["Referer"] = LEGACY_BASE_URL
		
		async with self.session.get(enable_pin_url, headers=headers) as resp:
			pass
			
		# Send "don't activate PIN" response
		headers.update({
			"Content-Type": "application/x-www-form-urlencoded",
			"Origin": "https://infomentor.se",
			"Referer": enable_pin_url,
		})
		
		pin_data = "__EVENTTARGET=aDontActivatePin&__EVENTARGUMENT=&__VIEWSTATE=%2FwEPDwULLTExNjgzNDAwMjdkZEPHrLmSUp3IKh%2FYk4WyEHsBQdMx&__VIEWSTATEGENERATOR=7189AD5F&__EVENTVALIDATION=%2FwEdAANT4hIcRyCqQMJVzIysT0grY9gRTC512bYsbnJ8gQeUrlnllTXttyQbAlgyFMdw9va%2BKdVQbZxLkS3XlIJc4f5qeOcV0g%3D%3D"
		
		async with self.session.post(enable_pin_url, headers=headers, data=pin_data) as resp:
			pass
	
	async def _get_callback_url(self, oauth_token: str) -> Optional[str]:
		"""Get the callback URL for completing authentication."""
		_LOGGER.debug("Getting callback URL")
		
		# Request login with OAuth
		login_url = f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true"
		
		headers = DEFAULT_HEADERS.copy()
		headers["Referer"] = "https://infomentor.se/Swedish/Production/mentor/Oryggi/PinLogin/EnablePin.aspx"
		
		async with self.session.get(login_url, headers=headers) as resp:
			_LOGGER.debug(f"Login OAuth page status: {resp.status}")
		
		# Send OAuth token to get callback URL - this should match the shell script exactly
		headers.update({
			"Content-Type": "application/x-www-form-urlencoded",
			"Origin": HUB_BASE_URL,
			"Referer": login_url,
			"Sec-Fetch-Mode": "navigate",
			"Sec-Fetch-Site": "same-site", 
			"Sec-Fetch-User": "?1",
		})
		
		data = f"oauth_token={oauth_token}"
		
		_LOGGER.debug(f"Sending OAuth token to: {LEGACY_BASE_URL}")
		_LOGGER.debug(f"OAuth token (first 10 chars): {oauth_token[:10]}...")
		
		async with self.session.post(
			LEGACY_BASE_URL,
			headers=headers,
			data=data,
			allow_redirects=False
		) as resp:
			_LOGGER.debug(f"OAuth response status: {resp.status}")
			_LOGGER.debug(f"OAuth response headers: {dict(resp.headers)}")
			
			location = resp.headers.get("Location")
			if location:
				_LOGGER.debug(f"Got callback URL: {location}")
				return location
			else:
				# If no location header, check the response content for clues
				text = await resp.text()
				_LOGGER.debug(f"No Location header. Response content (first 500 chars): {text[:500]}")
				
				# Check if we got redirected back to login (authentication failed)
				if "login" in text.lower() or "authentication" in text.lower():
					_LOGGER.error("Authentication failed - redirected back to login page")
					return None
				
		_LOGGER.error("No callback URL found in response")
		return None
	
	async def _execute_callback(self, callback_url: str) -> None:
		"""Execute the callback URL to complete authentication."""
		_LOGGER.debug("Executing callback")
		
		headers = DEFAULT_HEADERS.copy()
		headers["Referer"] = f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true"
		
		async with self.session.get(callback_url, headers=headers) as resp:
			pass
	
	async def _get_pupil_ids(self) -> list[str]:
		"""Extract pupil IDs from the hub page."""
		_LOGGER.debug("Getting pupil IDs")
		
		hub_url = f"{HUB_BASE_URL}/#/"
		headers = DEFAULT_HEADERS.copy()
		headers["Referer"] = f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true"
		
		async with self.session.get(hub_url, headers=headers) as resp:
			text = await resp.text()
			
		# Extract pupil IDs using regex pattern from original script
		pupil_pattern = r"/Account/PupilSwitcher/SwitchPupil/(\d+)"
		pupil_ids = list(set(re.findall(pupil_pattern, text)))
		
		_LOGGER.debug(f"Found pupil IDs: {pupil_ids}")
		return pupil_ids
	
	async def switch_pupil(self, pupil_id: str) -> bool:
		"""Switch to a specific pupil context.
		
		Args:
			pupil_id: ID of pupil to switch to
			
		Returns:
			True if switch successful
		"""
		if pupil_id not in self.pupil_ids:
			raise InfoMentorAuthError(f"Invalid pupil ID: {pupil_id}")
			
		switch_url = f"{HUB_BASE_URL}/Account/PupilSwitcher/SwitchPupil/{pupil_id}"
		
		headers = DEFAULT_HEADERS.copy()
		headers["Referer"] = f"{HUB_BASE_URL}/#/"
		
		async with self.session.get(switch_url, headers=headers) as resp:
			return resp.status == 200 