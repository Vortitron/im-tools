"""DataUpdateCoordinator for InfoMentor."""

import asyncio
import logging
from datetime import timedelta, datetime
from typing import Any, Dict, List, Optional

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .infomentor import InfoMentorClient
from .infomentor.exceptions import InfoMentorAuthError, InfoMentorConnectionError
from .infomentor.models import NewsItem, TimelineEntry, PupilInfo, ScheduleDay, TimetableEntry, TimeRegistrationEntry

from .const import DOMAIN, DEFAULT_UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class InfoMentorDataUpdateCoordinator(DataUpdateCoordinator):
	"""Class to manage fetching data from InfoMentor."""
	
	def __init__(self, hass: HomeAssistant, username: str, password: str) -> None:
		"""Initialise coordinator."""
		self.username = username
		self.password = password
		self.client: Optional[InfoMentorClient] = None
		self._session: Optional[aiohttp.ClientSession] = None
		self.pupil_ids: List[str] = []
		self.pupils_info: Dict[str, PupilInfo] = {}
		self._auth_failure_count = 0
		self._last_auth_failure: Optional[datetime] = None
		
		super().__init__(
			hass,
			_LOGGER,
			name=DOMAIN,
			update_interval=DEFAULT_UPDATE_INTERVAL,
		)
		
	async def _async_update_data(self) -> Dict[str, Any]:
		"""Update data via library."""
		try:
			# Check if we should back off due to recent auth failures
			if self._should_backoff():
				backoff_time = self._get_backoff_time()
				_LOGGER.warning(f"Backing off for {backoff_time} seconds due to recent authentication failures")
				raise UpdateFailed(f"Backing off due to authentication failures. Next retry in {backoff_time} seconds.")
			
			# Only setup client if not already initialized and authenticated
			if not self.client or not hasattr(self.client, 'auth') or not self.client.auth.authenticated:
				_LOGGER.debug("Setting up client (not initialized or not authenticated)")
				await self._setup_client()
			
			# Verify we still have valid authentication
			try:
				if not self.client.auth.authenticated:
					_LOGGER.debug("Authentication expired, re-authenticating")
					await self.client.login(self.username, self.password)
			except Exception as auth_err:
				_LOGGER.warning(f"Re-authentication failed, setting up new client: {auth_err}")
				await self._setup_client()
				
			data = {}
			
			# Get data for each pupil
			for pupil_id in self.pupil_ids:
				pupil_data = await self._get_pupil_data(pupil_id)
				data[pupil_id] = pupil_data
				
			# Reset auth failure count on successful update
			self._auth_failure_count = 0
			self._last_auth_failure = None
			
			_LOGGER.debug(f"Successfully updated data for {len(data)} pupils")
			return data
			
		except InfoMentorAuthError as err:
			self._record_auth_failure()
			_LOGGER.error(f"Authentication error during update: {err}")
			# Clear client to force re-setup on next update
			self.client = None
			raise ConfigEntryAuthFailed from err
		except InfoMentorConnectionError as err:
			_LOGGER.warning(f"Connection error during update: {err}")
			raise UpdateFailed(f"Error communicating with InfoMentor: {err}") from err
		except Exception as err:
			_LOGGER.error(f"Unexpected error during update: {err}")
			raise UpdateFailed(f"Unexpected error: {err}") from err
			
	async def _setup_client(self) -> None:
		"""Set up the InfoMentor client."""
		if not self._session:
			self._session = aiohttp.ClientSession()
			
		self.client = InfoMentorClient(self._session)
		
		# Enter the async context
		await self.client.__aenter__()
		
		# Authenticate
		await self.client.login(self.username, self.password)
		
		# Get pupil IDs
		self.pupil_ids = await self.client.get_pupil_ids()
		_LOGGER.info(f"Found {len(self.pupil_ids)} pupils: {self.pupil_ids}")
		
		# Get pupil info
		for pupil_id in self.pupil_ids:
			pupil_info = await self.client.get_pupil_info(pupil_id)
			if pupil_info:
				self.pupils_info[pupil_id] = pupil_info
				
	async def _get_pupil_data(self, pupil_id: str) -> Dict[str, Any]:
		"""Get data for a specific pupil."""
		if not self.client:
			raise UpdateFailed("Client not initialised")
			
		pupil_data = {
			"pupil_id": pupil_id,
			"pupil_info": self.pupils_info.get(pupil_id),
			"news": [],
			"timeline": [],
			"schedule": [],
			"today_schedule": None,
		}
		
		# Track which data sources succeeded
		success_count = 0
		total_sources = 3  # news, timeline, schedule
		
		try:
			# Get news
			news_items = await self.client.get_news(pupil_id)
			pupil_data["news"] = news_items
			success_count += 1
			_LOGGER.debug(f"Retrieved {len(news_items)} news items for pupil {pupil_id}")
			
		except Exception as err:
			_LOGGER.warning(f"Failed to get news for pupil {pupil_id}: {err}")
			
		try:
			# Get timeline
			timeline_entries = await self.client.get_timeline(pupil_id)
			pupil_data["timeline"] = timeline_entries
			success_count += 1
			_LOGGER.debug(f"Retrieved {len(timeline_entries)} timeline entries for pupil {pupil_id}")
			
		except Exception as err:
			_LOGGER.warning(f"Failed to get timeline for pupil {pupil_id}: {err}")
			
		try:
			# Get schedule (timetable and time registration)
			start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
			end_date = start_date + timedelta(weeks=2)  # Get 2 weeks of schedule
			
			schedule_days = await self.client.get_schedule(pupil_id, start_date, end_date)
			pupil_data["schedule"] = schedule_days
			success_count += 1
			_LOGGER.debug(f"Retrieved {len(schedule_days)} schedule days for pupil {pupil_id}")
			
			# Set today's schedule for easy access
			today = datetime.now().date()
			for day in schedule_days:
				if day.date.date() == today:
					pupil_data["today_schedule"] = day
					_LOGGER.debug(f"Today's schedule for pupil {pupil_id}: has_school={day.has_school}, has_preschool_or_fritids={day.has_preschool_or_fritids}")
					break
			
		except Exception as err:
			_LOGGER.warning(f"Failed to get schedule for pupil {pupil_id}: {err}")
			
		# Log overall success rate
		_LOGGER.info(f"Data retrieval for pupil {pupil_id}: {success_count}/{total_sources} sources successful")
		
		# If we failed to get any data at all, this might indicate a more serious issue
		if success_count == 0:
			_LOGGER.error(f"Failed to retrieve any data for pupil {pupil_id} - this may indicate authentication or connection issues")
			
		return pupil_data
		
	async def async_config_entry_first_refresh(self) -> None:
		"""Perform initial data fetch."""
		await self._setup_client()
		await super().async_config_entry_first_refresh()
		
	async def async_shutdown(self) -> None:
		"""Close the client session."""
		if self.client:
			try:
				await self.client.__aexit__(None, None, None)
			except Exception as err:
				_LOGGER.warning(f"Error closing InfoMentor client: {err}")
			finally:
				self.client = None
				
		if self._session:
			try:
				await self._session.close()
			except Exception as err:
				_LOGGER.warning(f"Error closing aiohttp session: {err}")
			finally:
				self._session = None
				
	async def async_refresh_pupil_data(self, pupil_id: str) -> None:
		"""Refresh data for a specific pupil."""
		if pupil_id not in self.pupil_ids:
			raise ValueError(f"Invalid pupil ID: {pupil_id}")
			
		if not self.client:
			await self._setup_client()
			
		pupil_data = await self._get_pupil_data(pupil_id)
		
		# Update coordinator data
		if self.data:
			self.data[pupil_id] = pupil_data
		else:
			self.data = {pupil_id: pupil_data}
			
		# Notify listeners
		self.async_update_listeners()
		
	def get_pupil_news_count(self, pupil_id: str) -> int:
		"""Get count of news items for a pupil."""
		if not self.data or pupil_id not in self.data:
			return 0
		return len(self.data[pupil_id].get("news", []))
		
	def get_pupil_timeline_count(self, pupil_id: str) -> int:
		"""Get count of timeline entries for a pupil."""
		if not self.data or pupil_id not in self.data:
			return 0
		return len(self.data[pupil_id].get("timeline", []))
		
	def get_latest_news_item(self, pupil_id: str) -> Optional[NewsItem]:
		"""Get the latest news item for a pupil."""
		if not self.data or pupil_id not in self.data:
			return None
			
		news_items = self.data[pupil_id].get("news", [])
		if not news_items:
			return None
			
		# Sort by published date and return the latest
		return max(news_items, key=lambda x: x.published_date)
		
	def get_latest_timeline_entry(self, pupil_id: str) -> Optional[TimelineEntry]:
		"""Get the latest timeline entry for a pupil."""
		if not self.data or pupil_id not in self.data:
			return None
			
		timeline_entries = self.data[pupil_id].get("timeline", [])
		if not timeline_entries:
			return None
			
		# Sort by date and return the latest
		return max(timeline_entries, key=lambda x: x.date)
		
	def get_pupil_schedule(self, pupil_id: str) -> List[ScheduleDay]:
		"""Get schedule for a pupil."""
		if not self.data or pupil_id not in self.data:
			return []
		return self.data[pupil_id].get("schedule", [])
		
	def get_schedule(self, pupil_id: str) -> List[ScheduleDay]:
		"""Get schedule for a pupil (alias for get_pupil_schedule for compatibility)."""
		return self.get_pupil_schedule(pupil_id)
		
	def get_today_schedule(self, pupil_id: str) -> Optional[ScheduleDay]:
		"""Get today's schedule for a pupil."""
		if not self.data or pupil_id not in self.data:
			return None
		return self.data[pupil_id].get("today_schedule")
		
	def has_school_today(self, pupil_id: str) -> bool:
		"""Check if pupil has school today."""
		today_schedule = self.get_today_schedule(pupil_id)
		return today_schedule.has_school if today_schedule else False
		
	def has_preschool_or_fritids_today(self, pupil_id: str) -> bool:
		"""Check if pupil has preschool or fritids today."""
		today_schedule = self.get_today_schedule(pupil_id)
		return today_schedule.has_preschool_or_fritids if today_schedule else False
		
	def _should_backoff(self) -> bool:
		"""Check if we should back off due to recent failures."""
		if not self._last_auth_failure:
			return False
		
		backoff_time = self._get_backoff_time()
		time_since_failure = (datetime.now() - self._last_auth_failure).total_seconds()
		return time_since_failure < backoff_time
		
	def _get_backoff_time(self) -> int:
		"""Get exponential backoff time in seconds."""
		# Exponential backoff: 5 minutes, 15 minutes, 45 minutes, then 2 hours
		if self._auth_failure_count <= 1:
			return 300  # 5 minutes
		elif self._auth_failure_count == 2:
			return 900  # 15 minutes
		elif self._auth_failure_count == 3:
			return 2700  # 45 minutes
		else:
			return 7200  # 2 hours
			
	def _record_auth_failure(self) -> None:
		"""Record an authentication failure for backoff calculations."""
		self._auth_failure_count += 1
		self._last_auth_failure = datetime.now()
		_LOGGER.warning(f"Authentication failure #{self._auth_failure_count} recorded") 