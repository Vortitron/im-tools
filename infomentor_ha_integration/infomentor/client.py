"""Main client for InfoMentor API."""

import json
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

import aiohttp

from .auth import InfoMentorAuth, HUB_BASE_URL, DEFAULT_HEADERS
from .models import NewsItem, TimelineEntry, PupilInfo, Assignment, AttendanceEntry
from .exceptions import InfoMentorAPIError, InfoMentorConnectionError, InfoMentorDataError

_LOGGER = logging.getLogger(__name__)


class InfoMentorClient:
	"""Client for interacting with InfoMentor API."""
	
	def __init__(self, session: Optional[aiohttp.ClientSession] = None):
		"""Initialise InfoMentor client.
		
		Args:
			session: Optional aiohttp session. If None, a new one will be created.
		"""
		self._session = session
		self._own_session = session is None
		self.auth: Optional[InfoMentorAuth] = None
		self.authenticated = False
		
	async def __aenter__(self):
		"""Async context manager entry."""
		if self._own_session:
			self._session = aiohttp.ClientSession()
		self.auth = InfoMentorAuth(self._session)
		return self
		
	async def __aexit__(self, exc_type, exc_val, exc_tb):
		"""Async context manager exit."""
		if self._own_session and self._session:
			await self._session.close()
			
	async def login(self, username: str, password: str) -> bool:
		"""Login to InfoMentor.
		
		Args:
			username: Username or email
			password: Password
			
		Returns:
			True if login successful
		"""
		if not self.auth:
			raise InfoMentorAPIError("Client not properly initialised")
			
		self.authenticated = await self.auth.login(username, password)
		return self.authenticated
		
	async def get_pupil_ids(self) -> List[str]:
		"""Get list of pupil IDs available for this account.
		
		Returns:
			List of pupil ID strings
		"""
		self._ensure_authenticated()
		return self.auth.pupil_ids.copy()
		
	async def switch_pupil(self, pupil_id: str) -> bool:
		"""Switch context to a specific pupil.
		
		Args:
			pupil_id: ID of pupil to switch to
			
		Returns:
			True if switch successful
		"""
		self._ensure_authenticated()
		return await self.auth.switch_pupil(pupil_id)
		
	async def get_news(self, pupil_id: Optional[str] = None) -> List[NewsItem]:
		"""Get news items for a pupil.
		
		Args:
			pupil_id: Optional pupil ID. If provided, switches to that pupil first.
			
		Returns:
			List of news items
		"""
		self._ensure_authenticated()
		
		if pupil_id:
			await self.switch_pupil(pupil_id)
			
		url = f"{HUB_BASE_URL}/Communication/News/GetNewsList"
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Accept": "application/json, text/javascript, */*; q=0.01",
			"X-Requested-With": "XMLHttpRequest",
		})
		
		try:
			async with self._session.get(url, headers=headers) as resp:
				if resp.status != 200:
					raise InfoMentorAPIError(f"Failed to get news: HTTP {resp.status}")
					
				data = await resp.json()
				return self._parse_news_data(data, pupil_id)
				
		except aiohttp.ClientError as e:
			raise InfoMentorConnectionError(f"Connection error: {e}") from e
		except json.JSONDecodeError as e:
			raise InfoMentorDataError(f"Failed to parse news data: {e}") from e
			
	async def get_timeline(self, pupil_id: Optional[str] = None, page: int = 1, page_size: int = 50) -> List[TimelineEntry]:
		"""Get timeline entries for a pupil.
		
		Args:
			pupil_id: Optional pupil ID. If provided, switches to that pupil first.
			page: Page number (default 1)
			page_size: Number of entries per page (default 50)
			
		Returns:
			List of timeline entries
		"""
		self._ensure_authenticated()
		
		if pupil_id:
			await self.switch_pupil(pupil_id)
			
		# First, initialise timeline app data
		app_data_url = f"{HUB_BASE_URL}/grouptimeline/grouptimeline/appData"
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Accept": "application/json, text/javascript, */*; q=0.01",
			"X-Requested-With": "XMLHttpRequest",
			"Content-Length": "0",
		})
		
		async with self._session.post(app_data_url, headers=headers) as resp:
			if resp.status != 200:
				_LOGGER.warning(f"Failed to initialise timeline app data: HTTP {resp.status}")
		
		# Get timeline entries
		timeline_url = f"{HUB_BASE_URL}/GroupTimeline/GroupTimeline/GetGroupTimelineEntries"
		headers.update({
			"Content-Type": "application/json; charset=UTF-8",
		})
		
		payload = {
			"page": page,
			"pageSize": page_size,
			"groupId": -1,
			"returnTimelineConfig": True
		}
		
		try:
			async with self._session.post(
				timeline_url, 
				headers=headers, 
				json=payload
			) as resp:
				if resp.status != 200:
					raise InfoMentorAPIError(f"Failed to get timeline: HTTP {resp.status}")
					
				data = await resp.json()
				return self._parse_timeline_data(data, pupil_id)
				
		except aiohttp.ClientError as e:
			raise InfoMentorConnectionError(f"Connection error: {e}") from e
		except json.JSONDecodeError as e:
			raise InfoMentorDataError(f"Failed to parse timeline data: {e}") from e
			
	async def get_pupil_info(self, pupil_id: str) -> Optional[PupilInfo]:
		"""Get information about a specific pupil.
		
		Args:
			pupil_id: ID of pupil
			
		Returns:
			PupilInfo object or None if not found
		"""
		self._ensure_authenticated()
		
		# For now, just return basic info. In the future, this could be enhanced
		# to fetch more detailed pupil information from specific endpoints
		if pupil_id in self.auth.pupil_ids:
			return PupilInfo(id=pupil_id)
		return None
		
	def _ensure_authenticated(self) -> None:
		"""Ensure client is authenticated."""
		if not self.authenticated or not self.auth:
			raise InfoMentorAPIError("Not authenticated. Call login() first.")
			
	def _parse_news_data(self, data: Dict[str, Any], pupil_id: Optional[str] = None) -> List[NewsItem]:
		"""Parse news data from API response.
		
		Args:
			data: Raw API response data
			pupil_id: Associated pupil ID
			
		Returns:
			List of NewsItem objects
		"""
		news_items = []
		
		try:
			# The exact structure will depend on the actual API response
			# This is a template that should be adjusted based on real data
			items = data.get("items", []) if isinstance(data, dict) else []
			
			for item in items:
				try:
					news_item = NewsItem(
						id=str(item.get("id", "")),
						title=item.get("title", ""),
						content=item.get("content", ""),
						published_date=self._parse_date(item.get("publishedDate", item.get("date"))),
						author=item.get("author"),
						category=item.get("category"),
						pupil_id=pupil_id
					)
					news_items.append(news_item)
				except (KeyError, ValueError) as e:
					_LOGGER.warning(f"Failed to parse news item: {e}")
					continue
					
		except Exception as e:
			_LOGGER.error(f"Failed to parse news data: {e}")
			raise InfoMentorDataError(f"Failed to parse news data: {e}") from e
			
		return news_items
		
	def _parse_timeline_data(self, data: Dict[str, Any], pupil_id: Optional[str] = None) -> List[TimelineEntry]:
		"""Parse timeline data from API response.
		
		Args:
			data: Raw API response data
			pupil_id: Associated pupil ID
			
		Returns:
			List of TimelineEntry objects
		"""
		timeline_entries = []
		
		try:
			# The exact structure will depend on the actual API response
			entries = data.get("entries", data.get("items", [])) if isinstance(data, dict) else []
			
			for entry in entries:
				try:
					timeline_entry = TimelineEntry(
						id=str(entry.get("id", "")),
						title=entry.get("title", ""),
						content=entry.get("content", entry.get("description", "")),
						date=self._parse_date(entry.get("date", entry.get("timestamp"))),
						entry_type=entry.get("type", "unknown"),
						pupil_id=pupil_id,
						author=entry.get("author")
					)
					timeline_entries.append(timeline_entry)
				except (KeyError, ValueError) as e:
					_LOGGER.warning(f"Failed to parse timeline entry: {e}")
					continue
					
		except Exception as e:
			_LOGGER.error(f"Failed to parse timeline data: {e}")
			raise InfoMentorDataError(f"Failed to parse timeline data: {e}") from e
			
		return timeline_entries
		
	def _parse_date(self, date_str: Optional[str]) -> datetime:
		"""Parse date string into datetime object.
		
		Args:
			date_str: Date string from API
			
		Returns:
			datetime object
		"""
		if not date_str:
			return datetime.now()
			
		# Try various date formats that InfoMentor might use
		date_formats = [
			"%Y-%m-%dT%H:%M:%S",
			"%Y-%m-%dT%H:%M:%SZ",
			"%Y-%m-%d %H:%M:%S",
			"%Y-%m-%d",
			"%d/%m/%Y",
			"%d.%m.%Y",
		]
		
		for fmt in date_formats:
			try:
				return datetime.strptime(date_str, fmt)
			except ValueError:
				continue
				
		# If all formats fail, return current time and log warning
		_LOGGER.warning(f"Failed to parse date: {date_str}")
		return datetime.now() 