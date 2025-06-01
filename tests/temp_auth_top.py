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

# Request delays to be respectful to InfoMentor servers
REQUEST_DELAY = 0.5  # Half second between requests
RETRY_DELAY = 2.0    # Two seconds before retries

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
		
	async def _delayed_request(self, method: str, url: str, delay: float = REQUEST_DELAY, **kwargs) -> aiohttp.ClientResponse:
		"""Make a request with a delay to be respectful to the server.
		
		Args:
			method: HTTP method (GET, POST, etc.)
			url: URL to request
			delay: Delay in seconds before making the request
			**kwargs: Additional arguments to pass to the request
			
		Returns:
			aiohttp.ClientResponse
		"""
		if delay > 0:
			await asyncio.sleep(delay)
		
		if method.upper() == 'GET':
			return await self.session.get(url, **kwargs)
		elif method.upper() == 'POST':
			return await self.session.post(url, **kwargs)
		else:
			raise ValueError(f"Unsupported HTTP method: {method}")
		
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
			
			# Step 3: Get pupil IDs with optimized approach (fewer requests)
