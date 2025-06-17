"""DataUpdateCoordinator for InfoMentor."""

import asyncio
import logging
from datetime import timedelta, datetime, time
from typing import Any, Dict, List, Optional

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .infomentor import InfoMentorClient
from .infomentor.exceptions import InfoMentorAuthError, InfoMentorConnectionError
from .infomentor.models import NewsItem, TimelineEntry, PupilInfo, ScheduleDay, TimetableEntry, TimeRegistrationEntry

from .const import (
	DOMAIN, 
	DEFAULT_UPDATE_INTERVAL, 
	FIRST_ATTEMPT_HOUR, 
	RETRY_INTERVAL_MINUTES, 
	MAX_RETRIES_PER_DAY
)

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
		
		# Smart retry tracking
		self._daily_retry_count = 0
		self._last_retry_date: Optional[str] = None
		self._last_successful_today_data_fetch: Optional[datetime] = None
		self._today_data_available = False
		
		# Set initial update interval using smart retry logic
		initial_interval = self._calculate_next_update_interval()
		
		super().__init__(
			hass,
			_LOGGER,
			name=DOMAIN,
			update_interval=initial_interval,
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
				
				# Additional validation - check if we have pupil IDs
				if not self.client.auth.pupil_ids:
					_LOGGER.warning("No pupil IDs available after authentication - re-initializing client")
					await self._setup_client()
					
					# If still no pupil IDs after re-setup, this indicates a more serious issue
					if not self.client.auth.pupil_ids:
						_LOGGER.error("Failed to retrieve pupil IDs after client re-initialization - authentication may have failed")
						# Don't attempt another re-setup to avoid infinite loops
						# Instead, raise an auth error to trigger the proper error handling
						self.client = None
						raise InfoMentorAuthError("Unable to retrieve pupil IDs after re-authentication")
					else:
						_LOGGER.info(f"Successfully recovered pupil IDs after re-initialization: {len(self.client.auth.pupil_ids)} pupils found")
			except Exception as auth_err:
				_LOGGER.warning(f"Re-authentication failed, setting up new client: {auth_err}")
				await self._setup_client()
				
			data = {}
			today_data_found = False
			
			# Get data for each pupil
			for pupil_id in self.pupil_ids:
				pupil_data = await self._get_pupil_data(pupil_id)
				data[pupil_id] = pupil_data
				
				# Check if we got today's schedule data
				if pupil_data.get("today_schedule"):
					today_data_found = True
				
			# Update retry tracking and interval
			self._update_retry_tracking(today_data_found)
			self._update_coordinator_interval()
			
			# Reset auth failure count on successful update
			self._auth_failure_count = 0
			self._last_auth_failure = None
			
			# Log successful data retrieval with more detail for troubleshooting
			total_entities = sum(len(pupil_data.get('news', [])) + len(pupil_data.get('timeline', [])) + len(pupil_data.get('schedule', [])) for pupil_data in data.values())
			_LOGGER.debug(f"Successfully updated data for {len(data)} pupils (today_data_found: {today_data_found}, total_entities: {total_entities})")
			
			# Log pupil IDs for verification
			if self.client and self.client.auth and self.client.auth.pupil_ids:
				_LOGGER.debug(f"Active pupil IDs: {self.client.auth.pupil_ids}")
			
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
		"""Set up the InfoMentor client with retry logic for pupil ID retrieval."""
		if not self._session:
			self._session = aiohttp.ClientSession()
			
		self.client = InfoMentorClient(self._session)
		
		# Enter the async context
		await self.client.__aenter__()
		
		# Authenticate
		await self.client.login(self.username, self.password)
		
		# Get pupil IDs with retry logic for transient failures
		max_retries = 3
		retry_delay = 2.0
		
		for attempt in range(max_retries):
			try:
				self.pupil_ids = await self.client.get_pupil_ids()
				if self.pupil_ids:
					_LOGGER.info(f"Found {len(self.pupil_ids)} pupils: {self.pupil_ids}")
					break
				else:
					_LOGGER.warning(f"Retrieved empty pupil list on attempt {attempt + 1}/{max_retries}")
					if attempt < max_retries - 1:
						await asyncio.sleep(retry_delay)
						retry_delay *= 1.5  # Exponential backoff
			except Exception as e:
				_LOGGER.warning(f"Failed to get pupil IDs on attempt {attempt + 1}/{max_retries}: {e}")
				if attempt < max_retries - 1:
					await asyncio.sleep(retry_delay)
					retry_delay *= 1.5  # Exponential backoff
				else:
					# If all retries failed, re-raise the exception
					raise
		
		# Final check after all retries
		if not self.pupil_ids:
			_LOGGER.error("No pupil IDs found after all retry attempts - this may indicate account issues or service problems")
			# Create a diagnostic report for troubleshooting
			try:
				auth_diag = await self.client.auth.diagnose_auth_state()
				_LOGGER.debug(f"Authentication diagnostic: {auth_diag}")
			except Exception as diag_err:
				_LOGGER.debug(f"Failed to get auth diagnostic: {diag_err}")
		
		# Get pupil info
		for pupil_id in self.pupil_ids:
			try:
				pupil_info = await self.client.get_pupil_info(pupil_id)
				if pupil_info:
					self.pupils_info[pupil_id] = pupil_info
			except Exception as e:
				_LOGGER.warning(f"Failed to get info for pupil {pupil_id}: {e}")

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
			_LOGGER.warning(f"Failed to retrieve any data for pupil {pupil_id}")
			
		return pupil_data
		
	async def async_config_entry_first_refresh(self) -> None:
		"""Perform first refresh of the coordinator."""
		await self.async_refresh()
		
	async def async_shutdown(self) -> None:
		"""Shutdown the coordinator and clean up resources."""
		if self.client:
			try:
				await self.client.__aexit__(None, None, None)
			except Exception as err:
				_LOGGER.warning(f"Error during client shutdown: {err}")
			finally:
				self.client = None
				
		if self._session and not self._session.closed:
			await self._session.close()
			self._session = None
			
	async def async_refresh_pupil_data(self, pupil_id: str) -> None:
		"""Refresh data for a specific pupil."""
		if pupil_id not in self.pupil_ids:
			_LOGGER.warning(f"Pupil {pupil_id} not found in available pupils")
			return
			
		try:
			pupil_data = await self._get_pupil_data(pupil_id)
			if self.data:
				self.data[pupil_id] = pupil_data
				self.async_update_listeners()
		except Exception as err:
			_LOGGER.error(f"Failed to refresh data for pupil {pupil_id}: {err}")
			
	# Utility methods for accessing data
	def get_pupil_news_count(self, pupil_id: str) -> int:
		"""Get count of news items for a pupil."""
		if self.data and pupil_id in self.data:
			return len(self.data[pupil_id].get("news", []))
		return 0
		
	def get_pupil_timeline_count(self, pupil_id: str) -> int:
		"""Get count of timeline entries for a pupil."""
		if self.data and pupil_id in self.data:
			return len(self.data[pupil_id].get("timeline", []))
		return 0
		
	def get_latest_news_item(self, pupil_id: str) -> Optional[NewsItem]:
		"""Get the latest news item for a pupil."""
		if self.data and pupil_id in self.data:
			news_items = self.data[pupil_id].get("news", [])
			if news_items:
				# Assume news items are sorted by date descending
				return news_items[0]
		return None
		
	def get_latest_timeline_entry(self, pupil_id: str) -> Optional[TimelineEntry]:
		"""Get the latest timeline entry for a pupil."""
		if self.data and pupil_id in self.data:
			timeline_entries = self.data[pupil_id].get("timeline", [])
			if timeline_entries:
				# Assume timeline entries are sorted by date descending
				return timeline_entries[0]
		return None
		
	def get_pupil_schedule(self, pupil_id: str) -> List[ScheduleDay]:
		"""Get schedule for a pupil."""
		if self.data and pupil_id in self.data:
			return self.data[pupil_id].get("schedule", [])
		return []
		
	def get_schedule(self, pupil_id: str) -> List[ScheduleDay]:
		"""Alias for get_pupil_schedule."""
		return self.get_pupil_schedule(pupil_id)
		
	def get_today_schedule(self, pupil_id: str) -> Optional[ScheduleDay]:
		"""Get today's schedule for a pupil."""
		if self.data and pupil_id in self.data:
			return self.data[pupil_id].get("today_schedule")
		return None
		
	def get_tomorrow_schedule(self, pupil_id: str) -> Optional[ScheduleDay]:
		"""Get tomorrow's schedule for a pupil."""
		schedule = self.get_pupil_schedule(pupil_id)
		tomorrow = datetime.now().date() + timedelta(days=1)
		
		for day in schedule:
			if day.date.date() == tomorrow:
				return day
		return None
		
	def has_school_today(self, pupil_id: str) -> bool:
		"""Check if pupil has school today."""
		today_schedule = self.get_today_schedule(pupil_id)
		return today_schedule.has_school if today_schedule else False
		
	def has_preschool_or_fritids_today(self, pupil_id: str) -> bool:
		"""Check if pupil has preschool or fritids today."""
		today_schedule = self.get_today_schedule(pupil_id)
		return today_schedule.has_preschool_or_fritids if today_schedule else False
		
	def has_school_tomorrow(self, pupil_id: str) -> bool:
		"""Check if pupil has school tomorrow."""
		tomorrow_schedule = self.get_tomorrow_schedule(pupil_id)
		return tomorrow_schedule.has_school if tomorrow_schedule else False
		
	def has_preschool_or_fritids_tomorrow(self, pupil_id: str) -> bool:
		"""Check if pupil has preschool or fritids tomorrow."""
		tomorrow_schedule = self.get_tomorrow_schedule(pupil_id)
		return tomorrow_schedule.has_preschool_or_fritids if tomorrow_schedule else False
		
	# Authentication failure handling
	def _should_backoff(self) -> bool:
		"""Check if we should back off due to recent authentication failures."""
		if self._auth_failure_count < 3:
			return False
			
		if not self._last_auth_failure:
			return False
			
		# Back off for exponentially increasing time based on failure count
		backoff_minutes = min(2 ** (self._auth_failure_count - 3), 60)  # Max 60 minutes
		return datetime.now() < self._last_auth_failure + timedelta(minutes=backoff_minutes)
		
	def _get_backoff_time(self) -> int:
		"""Get remaining backoff time in seconds."""
		if not self._last_auth_failure:
			return 0
			
		backoff_minutes = min(2 ** (self._auth_failure_count - 3), 60)
		backoff_end = self._last_auth_failure + timedelta(minutes=backoff_minutes)
		remaining = backoff_end - datetime.now()
		return max(0, int(remaining.total_seconds()))
		
	def _record_auth_failure(self) -> None:
		"""Record an authentication failure."""
		self._auth_failure_count += 1
		self._last_auth_failure = datetime.now()
		_LOGGER.warning(f"Authentication failure #{self._auth_failure_count} recorded")
		
	# Smart retry scheduling logic
	def _calculate_next_update_interval(self) -> timedelta:
		"""Calculate the next update interval based on smart retry logic."""
		now = datetime.now()
		today_str = now.strftime('%Y-%m-%d')
		
		# Check if we're on a new day - reset retry count
		if self._last_retry_date != today_str:
			self._daily_retry_count = 0
			self._last_retry_date = today_str
			self._today_data_available = False
			_LOGGER.debug(f"New day detected, resetting retry count")
		
		# If we already have today's data, use standard interval
		if self._today_data_available:
			_LOGGER.debug("Today's data already available, using standard 12-hour interval")
			return DEFAULT_UPDATE_INTERVAL
		
		# Calculate time until first attempt (2 AM) if we haven't reached it yet
		first_attempt_today = now.replace(hour=FIRST_ATTEMPT_HOUR, minute=0, second=0, microsecond=0)
		
		if now < first_attempt_today:
			# Before 2 AM - schedule for 2 AM
			interval = first_attempt_today - now
			_LOGGER.debug(f"Before first attempt time, scheduling for 2 AM (in {interval})")
			return interval
		
		# After 2 AM - check if we've hit max retries
		if self._daily_retry_count >= MAX_RETRIES_PER_DAY:
			# Hit max retries, wait until tomorrow's first attempt
			next_attempt = first_attempt_today + timedelta(days=1)
			interval = next_attempt - now
			_LOGGER.debug(f"Max retries reached, scheduling for tomorrow 2 AM (in {interval})")
			return interval
		
		# Within retry window - schedule next retry
		interval = timedelta(minutes=RETRY_INTERVAL_MINUTES)
		_LOGGER.debug(f"Within retry window (attempt {self._daily_retry_count + 1}/{MAX_RETRIES_PER_DAY}), scheduling retry in {interval}")
		return interval
		
	def _update_retry_tracking(self, today_data_found: bool) -> None:
		"""Update retry tracking based on whether today's data was found."""
		now = datetime.now()
		today_str = now.strftime('%Y-%m-%d')
		
		# Ensure we're tracking the current day
		if self._last_retry_date != today_str:
			self._daily_retry_count = 0
			self._last_retry_date = today_str
			self._today_data_available = False
		
		# Check if we're in the retry window (after 2 AM)
		first_attempt_today = now.replace(hour=FIRST_ATTEMPT_HOUR, minute=0, second=0, microsecond=0)
		if now >= first_attempt_today and not self._today_data_available:
			self._daily_retry_count += 1
			_LOGGER.debug(f"Incremented retry count to {self._daily_retry_count}")
		
		# Update data availability status
		if today_data_found:
			self._today_data_available = True
			self._last_successful_today_data_fetch = now
			_LOGGER.info("Today's data found, switching to standard update interval")
		
	def _update_coordinator_interval(self) -> None:
		"""Update the coordinator's update interval based on current state."""
		new_interval = self._calculate_next_update_interval()
		
		# Only update if the interval has changed significantly (more than 1 minute difference)
		if abs((new_interval - self.update_interval).total_seconds()) > 60:
			_LOGGER.debug(f"Updating coordinator interval from {self.update_interval} to {new_interval}")
			self.update_interval = new_interval
