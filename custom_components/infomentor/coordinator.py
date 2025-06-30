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
	RETRY_INTERVAL_HOURS,
	RETRY_INTERVAL_MINUTES_FAST,
	MAX_FAST_RETRIES,
	AUTH_BACKOFF_MINUTES,
	MAX_AUTH_FAILURES_BEFORE_BACKOFF
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
		
		# Schedule caching for today/tomorrow resilience
		self._cached_today_schedule: Dict[str, Optional[ScheduleDay]] = {}
		self._cached_tomorrow_schedule: Dict[str, Optional[ScheduleDay]] = {}
		self._last_schedule_cache_update: Optional[datetime] = None
		
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
				if not self.client.auth.authenticated or self.client.auth.is_auth_likely_expired():
					_LOGGER.debug("Authentication expired or likely expired, re-authenticating")
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
			
			# Update schedule cache if needed (around midnight) or if we have new data
			if self._should_update_schedule_cache() or data:
				_LOGGER.info("Updating schedule cache due to day change or new data")
				# Update retry tracking and interval
				self._update_retry_tracking(today_data_found)
				self._update_coordinator_interval()
				
				# Update schedule cache if needed (around midnight) or if we have new data
				if self._should_update_schedule_cache() or data:
					_LOGGER.info("Updating schedule cache due to day change or new data")
					self._update_schedule_cache()
				
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
			
			# Validate schedule data before accepting it
			valid_schedule_data = self._validate_schedule_data(schedule_days, pupil_id)
			
			if valid_schedule_data:
				pupil_data["schedule"] = schedule_days
				success_count += 1
				_LOGGER.debug(f"Retrieved {len(schedule_days)} schedule days for pupil {pupil_id}")
				
				# Set today's schedule for easy access
				today = datetime.now().date()
				for day in schedule_days:
					if day.date.date() == today:
						pupil_data["today_schedule"] = day
						_LOGGER.debug(f"Today's schedule for pupil {pupil_id}: has_school={day.has_school}, has_preschool_or_fritids={day.has_preschool_or_fritids}")
						
						# Log diagnostic info if today's schedule shows no activities
						if not day.has_school and not day.has_preschool_or_fritids:
							_LOGGER.warning(f"Today's schedule for pupil {pupil_id} shows no activities: "
										   f"timetable_entries={len(day.timetable_entries)}, "
										   f"time_registrations={len(day.time_registrations)}")
						break
			else:
				# If schedule data is invalid, preserve existing cached data if available
				_LOGGER.warning(f"Schedule data validation failed for pupil {pupil_id} - keeping existing cached data")
				if self.data and pupil_id in self.data:
					existing_schedule = self.data[pupil_id].get("schedule", [])
					existing_today = self.data[pupil_id].get("today_schedule")
					if existing_schedule:
						pupil_data["schedule"] = existing_schedule
						pupil_data["today_schedule"] = existing_today
						_LOGGER.info(f"Preserved existing schedule cache for pupil {pupil_id} ({len(existing_schedule)} days)")
			
		except Exception as err:
			_LOGGER.warning(f"Failed to get schedule for pupil {pupil_id}: {err}")
			# Preserve existing cached data if available
			if self.data and pupil_id in self.data:
				existing_schedule = self.data[pupil_id].get("schedule", [])
				existing_today = self.data[pupil_id].get("today_schedule")
				if existing_schedule:
					pupil_data["schedule"] = existing_schedule
					pupil_data["today_schedule"] = existing_today
					_LOGGER.info(f"Preserved existing schedule cache for pupil {pupil_id} due to retrieval failure")
		
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
		today_schedule = self.get_cached_today_schedule(pupil_id)
		return today_schedule.has_school if today_schedule else False
		
	def has_preschool_or_fritids_today(self, pupil_id: str) -> bool:
		"""Check if pupil has preschool or fritids today."""
		today_schedule = self.get_cached_today_schedule(pupil_id)
		return today_schedule.has_preschool_or_fritids if today_schedule else False
		
	def has_school_tomorrow(self, pupil_id: str) -> bool:
		"""Check if pupil has school tomorrow."""
		tomorrow_schedule = self.get_cached_tomorrow_schedule(pupil_id)
		return tomorrow_schedule.has_school if tomorrow_schedule else False
		
	def has_preschool_or_fritids_tomorrow(self, pupil_id: str) -> bool:
		"""Check if pupil has preschool or fritids tomorrow."""
		tomorrow_schedule = self.get_cached_tomorrow_schedule(pupil_id)
		return tomorrow_schedule.has_preschool_or_fritids if tomorrow_schedule else False
		
	# Authentication failure handling
	def _should_backoff(self) -> bool:
		"""Check if we should back off due to recent authentication failures."""
		if self._auth_failure_count < MAX_AUTH_FAILURES_BEFORE_BACKOFF:
			return False
			
		if not self._last_auth_failure:
			return False
			
		# Back off for a fixed time period (much simpler than exponential)
		backoff_end = self._last_auth_failure + timedelta(minutes=AUTH_BACKOFF_MINUTES)
		return datetime.now() < backoff_end
		
	def _get_backoff_time(self) -> int:
		"""Get remaining backoff time in seconds."""
		if not self._last_auth_failure:
			return 0
			
		backoff_end = self._last_auth_failure + timedelta(minutes=AUTH_BACKOFF_MINUTES)
		remaining = backoff_end - datetime.now()
		return max(0, int(remaining.total_seconds()))
		
	def _record_auth_failure(self) -> None:
		"""Record an authentication failure."""
		self._auth_failure_count += 1
		self._last_auth_failure = datetime.now()
		_LOGGER.warning(f"Authentication failure #{self._auth_failure_count} recorded")
		
	# Simplified retry scheduling logic
	def _calculate_next_update_interval(self) -> timedelta:
		"""Calculate the next update interval based on current state."""
		# If we have authentication failures, check if we're in backoff period
		if self._should_backoff():
			backoff_time = self._get_backoff_time()
			_LOGGER.debug(f"In auth backoff period, next retry in {backoff_time} seconds")
			return timedelta(seconds=backoff_time)
		
		# If we have good data and no recent failures, use standard interval
		if self._today_data_available and self._auth_failure_count == 0:
			_LOGGER.debug("Using standard 12-hour interval (data available, no auth failures)")
			return DEFAULT_UPDATE_INTERVAL
		
		# If we've had recent failures but less than max fast retries, retry quickly
		if self._daily_retry_count < MAX_FAST_RETRIES:
			interval = timedelta(minutes=RETRY_INTERVAL_MINUTES_FAST)
			_LOGGER.info(f"Using fast retry interval: {interval} (attempt {self._daily_retry_count + 1}/{MAX_FAST_RETRIES})")
			return interval
		
		# Otherwise, retry every hour
		interval = timedelta(hours=RETRY_INTERVAL_HOURS)
		_LOGGER.info(f"Using hourly retry interval: {interval}")
		return interval
		
	def _update_retry_tracking(self, today_data_found: bool) -> None:
		"""Update retry tracking based on whether today's data was found."""
		now = datetime.now()
		today_str = now.strftime('%Y-%m-%d')
		
		# Reset retry count on new day
		if self._last_retry_date != today_str:
			self._daily_retry_count = 0
			self._last_retry_date = today_str
			self._today_data_available = False
			_LOGGER.debug(f"New day detected, resetting retry count")
		
		# Increment retry count for this attempt
		self._daily_retry_count += 1
		
		# Update data availability status
		if today_data_found:
			self._today_data_available = True
			self._last_successful_today_data_fetch = now
			# Reset failure counts on success
			self._auth_failure_count = 0
			self._last_auth_failure = None
			self._daily_retry_count = 0  # Reset so we go back to standard interval
			_LOGGER.info("Today's data found successfully, resetting to standard update interval")
		else:
			_LOGGER.warning(f"Today's data not found, will retry (attempt #{self._daily_retry_count})")
		
	def _update_coordinator_interval(self) -> None:
		"""Update the coordinator's update interval based on current state."""
		new_interval = self._calculate_next_update_interval()
		if new_interval != self.update_interval:
			_LOGGER.debug(f"Updating coordinator interval from {self.update_interval} to {new_interval}")
			self.update_interval = new_interval
	
	def _update_schedule_cache(self) -> None:
		"""Update today/tomorrow schedule cache based on existing schedule data."""
		if not self.data:
			return
			
		now = datetime.now()
		today = now.date()
		tomorrow = (now + timedelta(days=1)).date()
		
		for pupil_id, pupil_data in self.data.items():
			schedule_days = pupil_data.get("schedule", [])
			
			# Find today's and tomorrow's schedules
			today_schedule = None
			tomorrow_schedule = None
			
			for day in schedule_days:
				if hasattr(day, 'date') and day.date:
					day_date = day.date.date() if hasattr(day.date, 'date') else day.date
					if day_date == today:
						today_schedule = day
					elif day_date == tomorrow:
						tomorrow_schedule = day
			
			self._cached_today_schedule[pupil_id] = today_schedule
			self._cached_tomorrow_schedule[pupil_id] = tomorrow_schedule
		
		self._last_schedule_cache_update = now
		_LOGGER.debug(f"Updated schedule cache at {now.strftime('%Y-%m-%d %H:%M:%S')} for {len(self.data)} pupils")
	
	def _should_update_schedule_cache(self) -> bool:
		"""Check if we should update the schedule cache (around midnight)."""
		if not self._last_schedule_cache_update:
			return True
			
		now = datetime.now()
		
		# If it's been more than 23 hours since last update, it's time to refresh
		if (now - self._last_schedule_cache_update).total_seconds() > 23 * 3600:
			return True
			
		# If we've crossed midnight since last update
		if now.date() != self._last_schedule_cache_update.date():
			return True
			
		return False
	
	def get_cached_today_schedule(self, pupil_id: str) -> Optional[ScheduleDay]:
		"""Get cached today's schedule, falling back to live data if cache miss."""
		# Try cache first
		if pupil_id in self._cached_today_schedule:
			cached = self._cached_today_schedule[pupil_id]
			if cached:
				_LOGGER.debug(f"Using cached today schedule for pupil {pupil_id}")
				return cached
		
		# Fall back to live data
		return self.get_today_schedule(pupil_id)
	
	def get_cached_tomorrow_schedule(self, pupil_id: str) -> Optional[ScheduleDay]:
		"""Get cached tomorrow's schedule, falling back to live data if cache miss."""
		# Try cache first
		if pupil_id in self._cached_tomorrow_schedule:
			cached = self._cached_tomorrow_schedule[pupil_id]
			if cached:
				_LOGGER.debug(f"Using cached tomorrow schedule for pupil {pupil_id}")
				return cached
		
		# Fall back to live data
		return self.get_tomorrow_schedule(pupil_id)

	def _validate_schedule_data(self, schedule_days: List[ScheduleDay], pupil_id: str) -> bool:
		"""Validate the schedule data before accepting it.
		
		Returns True if the schedule data looks valid, False if it seems to be missing key information.
		"""
		if not schedule_days:
			_LOGGER.warning(f"Schedule validation failed for pupil {pupil_id}: No schedule days returned")
			return False
		
		# Count days with actual data (either timetable entries or time registrations)
		days_with_data = 0
		days_with_timetable = 0
		days_with_time_reg = 0
		
		for day in schedule_days:
			has_any_data = len(day.timetable_entries) > 0 or len(day.time_registrations) > 0
			
			if has_any_data:
				days_with_data += 1
				if len(day.timetable_entries) > 0:
					days_with_timetable += 1
				if len(day.time_registrations) > 0:
					days_with_time_reg += 1
		
		# Log validation details for debugging
		_LOGGER.info(f"Schedule validation for pupil {pupil_id}: {len(schedule_days)} total days, "
					 f"{days_with_data} with data, {days_with_timetable} with timetable, "
					 f"{days_with_time_reg} with time registrations")
		
		# If we get absolutely no data for any day, this is likely an API failure
		if days_with_data == 0:
			_LOGGER.warning(f"Schedule validation failed for pupil {pupil_id}: No days contain any schedule data "
						   f"(neither timetable entries nor time registrations)")
			return False
		
		# If we have some data, the schedule is probably valid
		# Even if it's just a few days, that could be legitimate (e.g., holidays, part-time schedules)
		_LOGGER.info(f"Schedule validation passed for pupil {pupil_id}: Found data for {days_with_data} days")
		return True

	async def force_refresh(self, clear_cache: bool = True) -> None:
		"""Force a complete data refresh, optionally clearing caches.
		
		Args:
			clear_cache: Whether to clear existing cached schedule data
		"""
		_LOGGER.info(f"Force refresh requested (clear_cache={clear_cache})")
		
		if clear_cache:
			# Clear cached schedule data
			self._cached_today_schedule.clear()
			self._cached_tomorrow_schedule.clear()
			self._last_schedule_cache_update = None
			_LOGGER.info("Cleared cached schedule data")
		
		# Reset retry tracking to allow immediate refresh
		self._daily_retry_count = 0
		self._today_data_available = False
		self._auth_failure_count = 0
		self._last_auth_failure = None
		
		# Force immediate update
		await self.async_refresh()
		_LOGGER.info("Force refresh completed")

	async def debug_authentication(self) -> dict:
		"""Debug authentication process and return detailed information.
		
		This method performs authentication with extensive debugging and returns
		detailed information about each step of the process.
		"""
		_LOGGER.info("Starting debug authentication process")
		debug_info = {
			"oauth_token_extraction": "pending",
			"oauth_redirect_url": None,
			"oauth_token": None,
			"pupil_extraction": "pending",
			"pupil_ids": [],
			"errors": [],
			"debug_files_created": []
		}
		
		try:
			# Test OAuth token extraction specifically
			_LOGGER.info("Testing OAuth token extraction...")
			
			# Create a fresh session for debugging
			if self.client and self.client.session:
				oauth_token = await self.client.auth._get_oauth_token()
				if oauth_token:
					debug_info["oauth_token_extraction"] = "success"
					debug_info["oauth_token"] = oauth_token[:10] + "..." if len(oauth_token) > 10 else oauth_token
					_LOGGER.info(f"OAuth token extraction successful: {oauth_token[:10]}...")
				else:
					debug_info["oauth_token_extraction"] = "failed"
					debug_info["errors"].append("Failed to extract OAuth token")
					_LOGGER.error("OAuth token extraction failed")
			
			# Test full authentication
			_LOGGER.info("Testing full authentication process...")
			await self._setup_client()
			
			if self.client and self.client.auth.pupil_ids:
				debug_info["pupil_extraction"] = "success"
				debug_info["pupil_ids"] = self.client.auth.pupil_ids
				_LOGGER.info(f"Pupil extraction successful: {len(self.client.auth.pupil_ids)} pupils found")
			else:
				debug_info["pupil_extraction"] = "failed"
				debug_info["errors"].append("Failed to extract pupil IDs")
				_LOGGER.error("Pupil extraction failed")
			
			# Check for debug files
			import os
			debug_files = [
				"/tmp/infomentor_debug_initial.html",
				"/tmp/infomentor_debug_oauth.html", 
				"/tmp/infomentor_debug_dashboard.html"
			]
			
			for debug_file in debug_files:
				if os.path.exists(debug_file):
					debug_info["debug_files_created"].append(debug_file)
					_LOGGER.info(f"Debug file created: {debug_file}")
			
		except Exception as e:
			debug_info["errors"].append(f"Debug authentication failed: {e}")
			_LOGGER.error(f"Debug authentication failed: {e}")
		
		_LOGGER.info(f"Debug authentication complete: {debug_info}")
		return debug_info
