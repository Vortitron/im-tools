"""DataUpdateCoordinator for InfoMentor."""

import asyncio
import logging
import random
from datetime import timedelta, datetime, time
from typing import Any, Dict, List, Optional

import aiohttp
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components import persistent_notification
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.util import dt as dt_util

from .infomentor.client import InfoMentorClient
from .infomentor.exceptions import InfoMentorAuthError, InfoMentorConnectionError
from .infomentor.models import NewsItem, TimelineEntry, PupilInfo, ScheduleDay, TimetableEntry, TimeRegistrationEntry, InfoMentorNotification
from .storage import InfoMentorStorage
from .schedule_guard import (
	SCHEDULE_STATUS_CACHED,
	SCHEDULE_STATUS_FRESH,
	SCHEDULE_STATUS_MISSING,
	evaluate_schedule_completeness,
)

from .const import (
	DOMAIN,
	DEFAULT_UPDATE_INTERVAL,
	RETRY_INTERVAL_HOURS,
	RETRY_INTERVAL_MINUTES_FAST,
	MAX_FAST_RETRIES,
	AUTH_BACKOFF_MINUTES,
	MAX_AUTH_FAILURES_BEFORE_BACKOFF,
	EVENT_NEW_NOTIFICATION,
	CONF_NOTIFY_SERVICES,
	CONF_PERSISTENT_NOTIFICATION,
	NOTIFICATION_CHECK_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)

# Re-login for notification polling once the session is this old, even if
# fetches still appear to work.
NOTIFICATION_SESSION_MAX_AGE = timedelta(hours=8)
# Failed polls back off exponentially up to this, so a broken notification
# endpoint doesn't cause a full OAuth login every few minutes.
NOTIFICATION_MAX_BACKOFF = timedelta(hours=2)
# Upper bound on persisted notification IDs so storage doesn't grow forever.
MAX_SEEN_NOTIFICATION_IDS = 1000


def _local_now() -> datetime:
	"""Return the current time in HA's configured time zone as a naive datetime.

	Schedule dates from InfoMentor are naive local dates, so "today" must be
	computed in HA's time zone rather than the host's (often UTC).
	"""
	return dt_util.now().replace(tzinfo=None)


def _plain_text(html_text: Optional[str], limit: int = 160) -> str:
	"""Collapse HTML from InfoMentor into a short single-line summary."""
	if not html_text:
		return ""
	from bs4 import BeautifulSoup
	text = " ".join(BeautifulSoup(html_text, "html.parser").get_text(" ").split())
	return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _join_detail(*parts: Optional[str]) -> Optional[str]:
	"""Join non-empty, non-duplicate parts with " — "."""
	seen: List[str] = []
	for part in parts:
		part = (part or "").strip()
		if part and part not in seen:
			seen.append(part)
	return " — ".join(seen) or None


def _format_calendar_event(event: Dict[str, Any]) -> Optional[str]:
	"""E.g. "Studiedag · tor 24 sep (heldag) — Skolan är stängd."."""
	when = event.get("formattedStartDate") or event.get("startDate") or ""
	end = event.get("formattedEndDate")
	if end and end != when:
		when = f"{when} – {end}"
	if event.get("isAllDayEvent"):
		when = f"{when} (heldag)".strip()
	elif event.get("startTime"):
		when = f"{when} {event['startTime']}".strip()
	title = event.get("title") or ""
	head = f"{title} · {when}" if title and when else title or when
	return _join_detail(head, _plain_text(event.get("text") or event.get("description")))


class InfoMentorDataUpdateCoordinator(DataUpdateCoordinator):
	"""Class to manage fetching data from InfoMentor."""
	
	def __init__(self, hass: HomeAssistant, username: str, password: str, entry_id: str) -> None:
		"""Initialise coordinator."""
		self.username = username
		self.password = password
		self.entry_id = entry_id
		self.client: Optional[InfoMentorClient] = None
		# Created here (inside async_setup_entry) so HA detaches it on unload
		self._session: Optional[aiohttp.ClientSession] = async_create_clientsession(hass)
		self.pupil_ids: List[str] = []
		self.pupils_info: Dict[str, PupilInfo] = {}
		self._auth_failure_count = 0
		self._last_auth_failure: Optional[datetime] = None
		
		# Persistent storage
		self.storage = InfoMentorStorage(hass, entry_id)
		self._last_successful_update: Optional[datetime] = None
		self._using_cached_data = False
		self._last_auth_check: Optional[datetime] = None
		
		# Smart retry tracking
		self._daily_retry_count = 0
		self._last_retry_date: Optional[str] = None
		self._last_successful_today_data_fetch: Optional[datetime] = None
		self._today_data_available = False
		self._stale_retry_logged = False
		self._stale_retry_jitter_minutes: Optional[int] = None
		
		# Notification tracking (seen IDs are persisted so restarts don't re-push)
		self._seen_notification_ids: set[int] = set()
		self._seen_notification_ids_loaded = False
		self._notification_session_stale = False
		self._notification_failures = 0
		self._notification_retry_at: Optional[datetime] = None
		self._last_notification_check: Optional[datetime] = None
		self._notifications: List[InfoMentorNotification] = []

		# Ring buffer of recent diagnostic events, surfaced via the
		# "InfoMentor Diagnostic Log" sensor and the HA diagnostics download,
		# so users don't need shell access to the VM to see what's happening.
		self._diag_events: List[Dict[str, Any]] = []
		self._diag_events_max = 50

		# Schedule caching for today/tomorrow resilience
		self._cached_today_schedule: Dict[str, Optional[ScheduleDay]] = {}
		self._cached_tomorrow_schedule: Dict[str, Optional[ScheduleDay]] = {}
		self._last_schedule_cache_update: Optional[datetime] = None
		self._last_schedule_complete = False
		self._missing_schedule_pupils: List[str] = []
		self._stale_schedule_pupils: List[str] = []
		
		# Serialises InfoMentor API use: the server keeps one "current pupil" per
		# session, so a notification poll or login mid-refresh can corrupt it.
		self._api_lock = asyncio.Lock()
		self._unsub_timers: List[Any] = []
		
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
		async with self._api_lock:
			return await self._async_fetch_data()

	async def _async_fetch_data(self) -> Dict[str, Any]:
		"""Fetch data from InfoMentor; caller must hold ``_api_lock``."""
		# Try to load cached data first (this loads pupil IDs and names too)
		await self._load_cached_data_if_needed()
		
		try:
			# At startup, serve recent cached data straight away and authenticate
			# in the background. Later refreshes (scheduled, forced or from the
			# diagnostics buttons) must always fetch fresh data.
			if not self.data and await self.storage.has_recent_data(max_age_hours=72):
				cached_data = await self.storage.get_cached_pupil_data()
				if cached_data:
					_LOGGER.info("Have recent cached data (< 72 hours), loading from storage and skipping authentication attempt")
					self._using_cached_data = True
					try:
						self.data = self._deserialize_cached_data(cached_data)
						_LOGGER.debug(f"Successfully deserialized cached data for {len(self.data)} pupils")
					except Exception as e:
						_LOGGER.warning(f"Failed to deserialize cached data: {e}")
						self.data = None
					else:
						self._update_schedule_cache()
						self._schedule_refresh_after_cached_startup()
						self._start_background_task(self._background_auth_check(), "infomentor_background_auth")
						return self.data
			
			# Check if we should back off due to recent auth failures
			if self._should_backoff():
				backoff_time = self._get_backoff_time()
				_LOGGER.warning(f"Backing off for {backoff_time} seconds due to recent authentication failures")
				# Keep using existing data during backoff
				if self.data:
					_LOGGER.info("Using existing data during backoff period")
					self._using_cached_data = True
					return self.data
				raise UpdateFailed(f"Backing off due to authentication failures. Next retry in {backoff_time} seconds.")
			
			# Only setup client if not already initialized and authenticated
			just_set_up = False
			if not self.client or not hasattr(self.client, 'auth') or not self.client.auth.authenticated:
				_LOGGER.debug("Setting up client (not initialized or not authenticated)")
				try:
					await self._setup_client()
					just_set_up = True
				except (InfoMentorAuthError, InfoMentorConnectionError) as e:
					_LOGGER.warning(f"Failed to setup client: {e}")
					# Keep using existing data if available
					if self.data:
						_LOGGER.info("Using existing data after setup failure")
						self._using_cached_data = True
						return self.data
					raise
			
			# Verify we still have valid authentication
			try:
				# Skip when _setup_client() has just logged in, to avoid a second full login.
				# Only reuse a session if the previous refresh fully worked with it.
				if not just_set_up and (
					not self.client.auth.authenticated
					or self.client.auth.is_auth_likely_expired()
					or not self._last_schedule_complete
				):
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
			
			# Final validation before attempting data retrieval
			if not self.pupil_ids:
				_LOGGER.error("No pupil IDs available for data retrieval - cannot proceed")
				raise UpdateFailed("No pupil IDs available")
			
			# Validate each pupil ID before proceeding
			valid_pupil_ids = []
			for pupil_id in self.pupil_ids:
				if pupil_id and pupil_id != "None" and pupil_id.lower() != "none":
					valid_pupil_ids.append(pupil_id)
				else:
					_LOGGER.error(f"Invalid pupil ID found in list: {pupil_id!r}")
			
			if not valid_pupil_ids:
				_LOGGER.error("No valid pupil IDs found after validation")
				raise UpdateFailed("No valid pupil IDs")
			
			self.pupil_ids = valid_pupil_ids  # Update with only valid IDs
			
			data = {}
			any_today_schedule = False
			
			# Get data for each pupil
			for pupil_id in self.pupil_ids:
				pupil_data = await self._get_pupil_data(pupil_id)
				data[pupil_id] = pupil_data
				
				# Check if we got today's schedule data
				if pupil_data.get("today_schedule"):
					any_today_schedule = True
			
			is_complete_schedule, missing_pupils, stale_pupils = evaluate_schedule_completeness(self.pupil_ids, data)
			
			if not is_complete_schedule:
				if missing_pupils:
					_LOGGER.warning(f"Missing fresh schedules for pupils: {missing_pupils}")
				if stale_pupils:
					_LOGGER.warning(f"Used cached schedules for pupils: {stale_pupils}")
			else:
				_LOGGER.info("All pupils returned fresh schedules; marking data as up-to-date")
			
			self._last_schedule_complete = is_complete_schedule
			self._missing_schedule_pupils = list(missing_pupils)
			self._stale_schedule_pupils = list(stale_pupils)
			
			# Update retry tracking and coordinator interval using completeness flag
			self._update_retry_tracking(is_complete_schedule)
			
			# Update schedule cache if needed (around midnight) or if we have new data
			if self._should_update_schedule_cache() or data:
				_LOGGER.info("Updating schedule cache due to day change or new data")
				self._update_schedule_cache()
				
				# Reset auth failure count on successful update
				self._auth_failure_count = 0
				self._last_auth_failure = None
				
				# Log successful data retrieval with more detail for troubleshooting
				total_entities = sum(len(pupil_data.get('news', [])) + len(pupil_data.get('timeline', [])) + len(pupil_data.get('schedule', [])) for pupil_data in data.values())
				_LOGGER.debug(
					f"Successfully updated data for {len(data)} pupils "
					f"(complete_schedule: {is_complete_schedule}, any_today_schedule: {any_today_schedule}, "
					f"total_entities: {total_entities})"
				)
				
				# Log pupil IDs for verification
				if self.client and self.client.auth and self.client.auth.pupil_ids:
					_LOGGER.debug(f"Active pupil IDs: {self.client.auth.pupil_ids}")
			
			# Save successful data to persistent storage
			await self._save_data_to_storage(data, is_complete_schedule)
			# After saving, so the freshness timestamp used for the interval is current
			self._update_coordinator_interval()

			# Check for new notifications (non-critical)
			try:
				await self._check_notifications()
			except Exception as notif_err:
				_LOGGER.debug("Notification check failed (non-critical): %s", notif_err)

			return data
			
		except InfoMentorAuthError as err:
			self._record_auth_failure()
			_LOGGER.warning(f"Authentication error during update: {err}")
			# Clear client to force re-setup on next update
			self.client = None
			
			# Try to keep using existing data instead of failing
			if self.data:
				_LOGGER.warning("Authentication failed but keeping existing data")
				self._using_cached_data = True
				return self.data
			
			# Try to use cached data from storage
			cached_pupil_ids = await self.storage.get_pupil_ids()
			if cached_pupil_ids and not self.pupil_ids:
				_LOGGER.info("Loading pupil IDs from storage after auth failure")
				self.pupil_ids = cached_pupil_ids
				# Try again with cached pupil IDs - don't fail yet
				_LOGGER.info("Will retry with cached pupil IDs on next update")
				raise UpdateFailed(f"Authentication failed, will retry: {err}") from err
			
			# Only raise auth failed if we have no data to fall back on
			_LOGGER.error("No existing data available, authentication failure is critical")
			raise ConfigEntryAuthFailed from err
			
		except InfoMentorConnectionError as err:
			_LOGGER.warning(f"Connection error during update: {err}")
			
			# Try to keep using existing data for connection errors
			if self.data:
				_LOGGER.info("Connection error but keeping existing data")
				self._using_cached_data = True
				return self.data
			
			raise UpdateFailed(f"Error communicating with InfoMentor: {err}") from err
			
		except Exception as err:
			_LOGGER.warning(f"Unexpected error during update: {err}")
			
			# Try to keep using existing data for any unexpected errors
			if self.data:
				_LOGGER.info("Unexpected error but keeping existing data")
				self._using_cached_data = True
				return self.data
			
			raise UpdateFailed(f"Unexpected error: {err}") from err
			
	async def _setup_client(self) -> None:
		"""Set up the InfoMentor client with retry logic for pupil ID retrieval."""
		# Check if we're in the first 5 minutes of an hour (suspected server maintenance window)
		now = datetime.now()
		if now.minute < 5:
			# Check if we have recent cached data to use instead
			if await self.storage.has_recent_data(max_age_hours=24):
				_LOGGER.info(f"Avoiding authentication during first 5 minutes of hour (suspected maintenance window) - using cached data")
				# Load cached pupil IDs and names
				cached_pupil_ids = await self.storage.get_pupil_ids()
				if cached_pupil_ids:
					self.pupil_ids = cached_pupil_ids
					cached_pupil_names = await self.storage.get_pupil_names()
					for pupil_id in cached_pupil_ids:
						if pupil_id not in self.pupils_info:
							name = cached_pupil_names.get(pupil_id)
							if name:
								self.pupils_info[pupil_id] = PupilInfo(id=pupil_id, name=name)
							else:
								self.pupils_info[pupil_id] = PupilInfo(id=pupil_id)
					# Don't set up client, just return and use cached data
					return
			else:
				_LOGGER.warning(f"First 5 minutes of hour (suspected maintenance window) but no cached data available - proceeding with authentication anyway")
		
		if not self._session:
			# Dedicated session so this account's cookie jar isn't shared with other
			# InfoMentor accounts or integrations using HA's global session.
			self._session = async_create_clientsession(self.hass)
			
		self.client = InfoMentorClient(self._session, self.storage)
		
		# Enter the async context
		await self.client.__aenter__()
		
		reused_session = False
		
		if self.client.auth and self.storage:
			try:
				reused_session = await self.client.try_restore_session()
			except Exception as err:
				_LOGGER.debug(f"Stored session reuse failed: {err}")
		
		if not reused_session:
			# Authenticate
			await self.client.login(self.username, self.password)
		else:
			_LOGGER.info("Reused stored InfoMentor session cookies; skipping full login")
		
		# Get pupil IDs with retry logic for transient failures
		# If authentication succeeds but we get no pupils, that's an InfoMentor server issue
		max_retries = 5  # Increased retries for server issues
		retry_delay = 3.0  # Start with 3 seconds
		
		for attempt in range(max_retries):
			try:
				self.pupil_ids = await self.client.get_pupil_ids()
				if self.pupil_ids:
					_LOGGER.info(f"Found {len(self.pupil_ids)} pupils: {self.pupil_ids}")
					break
				else:
					_LOGGER.warning(f"Authentication succeeded but retrieved empty pupil list on attempt {attempt + 1}/{max_retries} - InfoMentor server issue")
					if attempt < max_retries - 1:
						_LOGGER.info(f"Retrying in {retry_delay:.1f} seconds...")
						await asyncio.sleep(retry_delay)
						retry_delay *= 1.5  # Exponential backoff
					else:
						_LOGGER.error(f"Failed to get pupil IDs after {max_retries} attempts - InfoMentor servers appear to be having issues")
			except InfoMentorAuthError as e:
				if reused_session:
					_LOGGER.info(f"Stored session rejected while fetching pupil IDs ({e}); performing full login")
					reused_session = False
					await self.client.login(self.username, self.password)
					continue
				_LOGGER.warning(f"Failed to get pupil IDs on attempt {attempt + 1}/{max_retries}: {e}")
				if attempt < max_retries - 1:
					_LOGGER.info(f"Retrying in {retry_delay:.1f} seconds...")
					await asyncio.sleep(retry_delay)
					retry_delay *= 1.5
				else:
					raise
			except Exception as e:
				_LOGGER.warning(f"Failed to get pupil IDs on attempt {attempt + 1}/{max_retries}: {e}")
				if attempt < max_retries - 1:
					_LOGGER.info(f"Retrying in {retry_delay:.1f} seconds...")
					await asyncio.sleep(retry_delay)
					retry_delay *= 1.5  # Exponential backoff
				else:
					# If all retries failed, re-raise the exception
					raise
		
		# Final check after all retries
		if not self.pupil_ids:
			_LOGGER.error("No pupil IDs found after all retry attempts - this indicates InfoMentor server issues")
			# Try to load from cache as fallback
			cached_pupil_ids = await self.storage.get_pupil_ids()
			if cached_pupil_ids:
				_LOGGER.warning(f"Using cached pupil IDs as fallback: {cached_pupil_ids}")
				self.pupil_ids = cached_pupil_ids
				# Also load cached pupil info
				cached_pupil_names = await self.storage.get_pupil_names()
				for pupil_id in cached_pupil_ids:
					if pupil_id not in self.pupils_info:
						name = cached_pupil_names.get(pupil_id)
						if name:
							self.pupils_info[pupil_id] = PupilInfo(id=pupil_id, name=name)
						else:
							self.pupils_info[pupil_id] = PupilInfo(id=pupil_id)
				return  # Use cached data and continue
			else:
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
			
		# Validate pupil_id before making any API calls
		if not pupil_id or pupil_id == "None" or pupil_id.lower() == "none":
			_LOGGER.error(f"Invalid pupil ID received: {pupil_id!r}")
			raise UpdateFailed(f"Invalid pupil ID: {pupil_id}")
			
		if pupil_id not in self.pupil_ids:
			_LOGGER.error(f"Pupil ID {pupil_id} not found in available pupils: {self.pupil_ids}")
			raise UpdateFailed(f"Pupil ID {pupil_id} not in available pupils")
		
		pupil_data = {
			"pupil_id": pupil_id,
			"pupil_info": self.pupils_info.get(pupil_id),
			"news": [],
			"timeline": [],
			"schedule": [],
			"today_schedule": None,
			"schedule_status": SCHEDULE_STATUS_MISSING,
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
			pupil_data["news"] = self._previous_pupil_items(pupil_id, "news")
			
		try:
			# Get timeline
			timeline_entries = await self.client.get_timeline(pupil_id)
			pupil_data["timeline"] = timeline_entries
			success_count += 1
			_LOGGER.debug(f"Retrieved {len(timeline_entries)} timeline entries for pupil {pupil_id}")
			
		except Exception as err:
			_LOGGER.warning(f"Failed to get timeline for pupil {pupil_id}: {err}")
			pupil_data["timeline"] = self._previous_pupil_items(pupil_id, "timeline")
			
		try:
			# Get schedule (timetable and time registration)
			start_date = _local_now().replace(hour=0, minute=0, second=0, microsecond=0)
			
			# Calculate end date to ensure we get through the end of the following week
			# This prevents Monday cache issues by always having the following week's data
			current_weekday = start_date.weekday()  # Monday = 0, Sunday = 6
			days_until_next_sunday = 13 - current_weekday  # Days to get to the Sunday of next week
			end_date = start_date + timedelta(days=days_until_next_sunday)
			
			schedule_days = await self.client.get_schedule(pupil_id, start_date, end_date)
			
			# Validate schedule data before accepting it
			valid_schedule_data = self._validate_schedule_data(schedule_days, pupil_id)
			
			if valid_schedule_data:
				pupil_data["schedule"] = schedule_days
				pupil_data["schedule_status"] = SCHEDULE_STATUS_FRESH
				success_count += 1
				_LOGGER.debug(f"Retrieved {len(schedule_days)} schedule days for pupil {pupil_id}")
				
				# Set today's schedule for easy access
				today = _local_now().date()
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
						pupil_data["schedule_status"] = SCHEDULE_STATUS_CACHED
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
					pupil_data["schedule_status"] = SCHEDULE_STATUS_CACHED
					_LOGGER.info(f"Preserved existing schedule cache for pupil {pupil_id} due to retrieval failure")
		
		# Log overall success rate
		_LOGGER.info(f"Data retrieval for pupil {pupil_id}: {success_count}/{total_sources} sources successful")
		
		# If we failed to get any data at all, this might indicate a more serious issue
		if success_count == 0:
			_LOGGER.warning(f"Failed to retrieve any data for pupil {pupil_id}")
			
		return pupil_data
	
	def _start_background_task(self, coro: Any, name: str) -> None:
		"""Run a task that HA cancels when this config entry unloads."""
		entry = self.hass.config_entries.async_get_entry(self.entry_id)
		if entry is not None:
			entry.async_create_background_task(self.hass, coro, name)
		else:
			self.hass.async_create_task(coro)

	def _previous_pupil_items(self, pupil_id: str, key: str) -> list:
		"""Return the last known list for a pupil (e.g. news) so a failed fetch doesn't blank it."""
		if self.data and pupil_id in self.data:
			return list(self.data[pupil_id].get(key) or [])
		return []
		
	async def async_config_entry_first_refresh(self) -> None:
		"""Perform first refresh of the coordinator with improved error handling."""
		try:
			# Use asyncio.wait_for with a reasonable timeout for the first refresh
			await asyncio.wait_for(self.async_refresh(), timeout=90.0)
			_LOGGER.debug("First refresh completed successfully")
		except asyncio.TimeoutError:
			_LOGGER.warning("First refresh timed out after 90 seconds - continuing with setup, will retry in background")
			# Don't raise the timeout error during setup - let it retry in the background
		except asyncio.CancelledError:
			_LOGGER.warning("First refresh was cancelled - continuing with setup, will retry in background")
			# Don't raise the cancelled error during setup - let it retry in the background
		except (InfoMentorAuthError, ConfigEntryAuthFailed) as err:
			_LOGGER.error(f"Authentication failed during first refresh: {err}")
			# Re-raise auth errors as they indicate credential problems
			raise
		except Exception as err:
			_LOGGER.warning(f"First refresh failed with error: {err} - continuing with setup, will retry in background")
			# Log other errors but don't fail the setup - let background updates handle retries
		
	def _deserialize_cached_data(self, cached_dict_data: Dict[str, Any]) -> Dict[str, Any]:
		"""Convert cached dict data back to proper model objects.
		
		Args:
			cached_dict_data: Dictionary data loaded from JSON storage
			
		Returns:
			Dictionary with proper model objects
		"""
		deserialized = {}
		
		for pupil_id, pupil_data in cached_dict_data.items():
			if not isinstance(pupil_data, dict):
				continue
				
			deserialized_pupil_data = {
				"pupil_id": pupil_id,
				"pupil_info": None,
				"news": [],
				"timeline": [],
				"schedule": [],
				"today_schedule": None,
			}
			
			# Deserialize pupil info
			if pupil_data.get("pupil_info"):
				info = pupil_data["pupil_info"]
				if isinstance(info, dict):
					deserialized_pupil_data["pupil_info"] = PupilInfo(
						id=info.get("id", pupil_id),
						name=info.get("name"),
						class_name=info.get("class_name"),
						school=info.get("school"),
					)
			
			# Deserialize news items
			for news_dict in pupil_data.get("news", []):
				if isinstance(news_dict, dict):
					try:
						deserialized_pupil_data["news"].append(NewsItem(
							id=news_dict.get("id", ""),
							title=news_dict.get("title", ""),
							content=news_dict.get("content", ""),
							published_date=datetime.fromisoformat(news_dict["published_date"]) if "published_date" in news_dict else datetime.now(),
							author=news_dict.get("author"),
							category=news_dict.get("category"),
							pupil_id=news_dict.get("pupil_id", pupil_id),
						))
					except Exception as e:
						_LOGGER.debug(f"Failed to deserialize news item: {e}")
			
			# Deserialize timeline entries
			for timeline_dict in pupil_data.get("timeline", []):
				if isinstance(timeline_dict, dict):
					try:
						deserialized_pupil_data["timeline"].append(TimelineEntry(
							id=timeline_dict.get("id", ""),
							title=timeline_dict.get("title", ""),
							content=timeline_dict.get("content", ""),
							date=datetime.fromisoformat(timeline_dict["date"]) if "date" in timeline_dict else datetime.now(),
							entry_type=timeline_dict.get("entry_type", ""),
							pupil_id=timeline_dict.get("pupil_id", pupil_id),
							author=timeline_dict.get("author"),
						))
					except Exception as e:
						_LOGGER.debug(f"Failed to deserialize timeline entry: {e}")
			
			# Deserialize schedule days
			for day_dict in pupil_data.get("schedule", []):
				if isinstance(day_dict, dict):
					try:
						# Deserialize timetable entries
						timetable_entries = []
						for entry_dict in day_dict.get("timetable_entries", []):
							if isinstance(entry_dict, dict):
								timetable_entries.append(TimetableEntry(
									id=entry_dict.get("id", ""),
									title=entry_dict.get("title", ""),
									date=datetime.fromisoformat(entry_dict["date"]) if "date" in entry_dict else datetime.now(),
									subject=entry_dict.get("subject"),
									start_time=time.fromisoformat(entry_dict["start_time"]) if entry_dict.get("start_time") else None,
									end_time=time.fromisoformat(entry_dict["end_time"]) if entry_dict.get("end_time") else None,
									teacher=entry_dict.get("teacher"),
									room=entry_dict.get("room"),
									description=entry_dict.get("description"),
									entry_type=entry_dict.get("entry_type"),
									is_all_day=entry_dict.get("is_all_day", False),
									pupil_id=entry_dict.get("pupil_id", pupil_id),
								))
						
						# Deserialize time registrations
						time_registrations = []
						for reg_dict in day_dict.get("time_registrations", []):
							if isinstance(reg_dict, dict):
								time_registrations.append(TimeRegistrationEntry(
									id=reg_dict.get("id", ""),
									date=datetime.fromisoformat(reg_dict["date"]) if "date" in reg_dict else datetime.now(),
									start_time=time.fromisoformat(reg_dict["start_time"]) if reg_dict.get("start_time") else None,
									end_time=time.fromisoformat(reg_dict["end_time"]) if reg_dict.get("end_time") else None,
									status=reg_dict.get("status"),
									comment=reg_dict.get("comment"),
									is_locked=reg_dict.get("is_locked", False),
									is_school_closed=reg_dict.get("is_school_closed", False),
									on_leave=reg_dict.get("on_leave", False),
									can_edit=reg_dict.get("can_edit", True),
									school_closed_reason=reg_dict.get("school_closed_reason"),
									pupil_id=reg_dict.get("pupil_id", pupil_id),
									registration_type=reg_dict.get("registration_type"),
								))
						
						# Create ScheduleDay object
						schedule_day = ScheduleDay(
							date=datetime.fromisoformat(day_dict["date"]) if "date" in day_dict else datetime.now(),
							pupil_id=pupil_id,
							timetable_entries=timetable_entries,
							time_registrations=time_registrations,
						)
						deserialized_pupil_data["schedule"].append(schedule_day)
						
						# Check if this is today's schedule
						if day_dict.get("date"):
							day_date = datetime.fromisoformat(day_dict["date"]).date()
							if day_date == _local_now().date():
								deserialized_pupil_data["today_schedule"] = schedule_day
					except Exception as e:
						_LOGGER.debug(f"Failed to deserialize schedule day: {e}")
			
			deserialized[pupil_id] = deserialized_pupil_data
		
		return deserialized
	
	async def _load_cached_data_if_needed(self) -> None:
		"""Load cached data from storage if available."""
		try:
			# Load pupil IDs and names from storage
			cached_pupil_ids = await self.storage.get_pupil_ids()
			cached_pupil_names = await self.storage.get_pupil_names()
			
			if cached_pupil_ids and not self.pupil_ids:
				_LOGGER.info(f"Loaded {len(cached_pupil_ids)} pupil IDs from storage")
				self.pupil_ids = cached_pupil_ids
				
				# Create PupilInfo objects from cached names
				for pupil_id in cached_pupil_ids:
					if pupil_id not in self.pupils_info:
						name = cached_pupil_names.get(pupil_id)
						if name:
							self.pupils_info[pupil_id] = PupilInfo(id=pupil_id, name=name)
						else:
							self.pupils_info[pupil_id] = PupilInfo(id=pupil_id)
			
			# Load timestamp of last complete schedule update (fallback to legacy key once)
			last_complete_update = await self.storage.get_last_complete_schedule_update()
			if last_complete_update:
				self._last_successful_update = last_complete_update
			else:
				self._last_successful_update = await self.storage.get_last_successful_update()
				if self._last_successful_update:
					_LOGGER.debug("Using legacy last_successful_update timestamp until a complete schedule refresh occurs")
			
			if self._last_successful_update:
				from datetime import timezone
				last_update = self._last_successful_update
				if last_update.tzinfo is None:
					last_update = last_update.replace(tzinfo=timezone.utc)
				
				now_utc = datetime.now(timezone.utc)
				age = now_utc - last_update
				_LOGGER.info(f"Last complete schedule refresh was {age.total_seconds() / 3600:.1f} hours ago")
				
		except Exception as e:
			_LOGGER.warning(f"Error loading cached data: {e}")
	
	# ------------------------------------------------------------------
	# Notification helpers
	# ------------------------------------------------------------------

	async def _check_notifications(self, force: bool = False) -> None:
		"""Fetch InfoMentor notifications and fire HA events for new ones."""
		if not self.client:
			return

		now = datetime.now()
		if (
			not force
			and self._last_notification_check
			and (now - self._last_notification_check).total_seconds()
			< NOTIFICATION_CHECK_INTERVAL_MINUTES * 60
		):
			return

		self._last_notification_check = now

		try:
			notifications = await self.client.get_notifications()
		except Exception as err:
			_LOGGER.debug("Could not fetch notifications: %s", err)
			# Next poll re-logs in rather than retrying a dead session
			self._notification_session_stale = True
			return

		self._notification_session_stale = False
		self._notifications = notifications

		first_run = await self._load_seen_notification_ids()
		new_notifications: List[InfoMentorNotification] = []
		seen_changed = False

		for notif in notifications:
			if notif.id not in self._seen_notification_ids:
				self._seen_notification_ids.add(notif.id)
				seen_changed = True
				if notif.is_new and not first_run:
					new_notifications.append(notif)

		if seen_changed or first_run:
			await self._save_seen_notification_ids()
		if first_run:
			_LOGGER.info(
				"First notification check: recorded %d existing notifications without pushing them",
				len(notifications),
			)

		if not new_notifications:
			return

		_LOGGER.info("Found %d new InfoMentor notifications", len(new_notifications))

		for notif in new_notifications:
			push = await self._describe_notification(notif)
			event_data = {
				"id": notif.id,
				"title": notif.title,
				"sub_title": notif.sub_title,
				"detail": push["detail"],
				"date_sent": notif.date_sent.isoformat(),
				"app_type": notif.app_type,
				"notification_type": notif.notification_type,
				"url": notif.full_url,
				"pupil_id": notif.pupil_id,
				"pupil_name": push["pupil_name"],
				"pupil_im2_id": notif.pupil_im2_id,
				"entity_type": notif.entity_type,
			}
			self.hass.bus.async_fire(EVENT_NEW_NOTIFICATION, event_data)
			_LOGGER.debug("Fired %s event for notification %d", EVENT_NEW_NOTIFICATION, notif.id)
			await self._deliver_notification(push)

	async def _load_seen_notification_ids(self) -> bool:
		"""Load persisted notification IDs once; return True if none were ever stored.

		On the very first check we only record what is already there, so that
		installing the integration doesn't push every unread notification.
		"""
		if self._seen_notification_ids_loaded:
			return False
		self._seen_notification_ids_loaded = True
		try:
			stored = await self.storage.get_seen_notification_ids()
		except Exception as err:
			_LOGGER.debug("Could not load seen notification IDs: %s", err)
			stored = None
		if stored is None:
			return True
		self._seen_notification_ids.update(stored)
		return False

	async def _save_seen_notification_ids(self) -> None:
		"""Persist seen notification IDs, keeping only the most recent ones."""
		if len(self._seen_notification_ids) > MAX_SEEN_NOTIFICATION_IDS:
			newest = sorted(self._seen_notification_ids, reverse=True)[:MAX_SEEN_NOTIFICATION_IDS]
			self._seen_notification_ids = set(newest)
		try:
			await self.storage.save_seen_notification_ids(sorted(self._seen_notification_ids))
		except Exception as err:
			_LOGGER.debug("Could not save seen notification IDs: %s", err)

	def _pupil_display_name(self, pupil_id: Optional[str]) -> str:
		"""First name for push titles ("Lyeklint Hancock, Felix" -> "Felix")."""
		info = self.pupils_info.get(pupil_id) if pupil_id else None
		if not info or not info.name:
			return ""
		last, sep, first = info.name.partition(",")
		return first.strip() if sep and first.strip() else info.name

	async def _describe_notification(self, notif: InfoMentorNotification) -> Dict[str, Any]:
		"""Build push title/message; the notification itself only has a generic title."""
		detail = None
		try:
			detail = await self._notification_detail(notif)
		except Exception as err:
			_LOGGER.debug("Could not look up details for notification %d: %s", notif.id, err)
		pupil_name = self._pupil_display_name(notif.pupil_id)
		fallback = " — ".join(p for p in (notif.sub_title, notif.date_sent.strftime("%Y-%m-%d %H:%M")) if p)
		return {
			"title": f"{pupil_name}: {notif.title}" if pupil_name else f"InfoMentor: {notif.title}",
			"message": detail or fallback,
			"detail": detail,
			"pupil_name": pupil_name,
			"url": notif.full_url,
			"tag": f"infomentor_{notif.id}",
		}

	async def _notification_detail(self, notif: InfoMentorNotification) -> Optional[str]:
		"""Look up what a notification is about (event, news item or learning-log post)."""
		if not self.client:
			return None
		pupil_id = notif.pupil_id if notif.pupil_id in self.pupil_ids else None

		if notif.app_type == "News":
			news_id = notif.url_path_id
			if not news_id:
				return None
			items = self._previous_pupil_items(pupil_id, "news") if pupil_id else []
			item = next((n for n in items if n.id == news_id), None)
			if item is None:
				item = next((n for n in await self.client.get_news(pupil_id) if n.id == news_id), None)
			return _join_detail(item.title, _plain_text(item.content)) if item else None

		if notif.app_type == "CalendarV2":
			year, week = notif.url_param("selectedYear"), notif.url_param("selectedWeek")
			if year and week and year.isdigit() and week.isdigit():
				start = datetime.fromisocalendar(int(year), int(week), 1)
			else:
				start = notif.date_sent.replace(hour=0, minute=0, second=0, microsecond=0)
			entries = await self.client.get_calendar_entries(pupil_id, start, start + timedelta(days=7))
			event_id = notif.url_param("eventId")
			if event_id:
				event = next((e for e in entries if str(e.get("id")) == event_id), None)
				return _format_calendar_event(event) if event else None
			# "New calendar events" only points at a week: list what's in it
			titles = [e.get("title") for e in entries if e.get("title")]
			if not titles:
				return None
			more = f" (+{len(titles) - 3})" if len(titles) > 3 else ""
			return f"v.{week}: " + ", ".join(titles[:3]) + more if week else ", ".join(titles[:3]) + more

		if notif.app_type == "LearnLog":
			posts = await self.client.get_learnlogs(pupil_id)
			if posts:
				post = posts[0]  # newest first
				return _join_detail(post.get("title"), post.get("subjectsCoursesDisplayString") or _plain_text(post.get("text")))

		return None

	def _notification_targets(self) -> tuple[List[str], bool]:
		"""Configured notify services and whether to also show HA persistent notifications."""
		entry = self.hass.config_entries.async_get_entry(self.entry_id)
		if not entry:
			return [], False
		raw = entry.options.get(CONF_NOTIFY_SERVICES) or []
		# Older versions stored a comma-separated string
		if isinstance(raw, str):
			raw = raw.split(",")
		services = [str(svc).strip() for svc in raw if str(svc).strip()]
		return services, bool(entry.options.get(CONF_PERSISTENT_NOTIFICATION, False))

	async def _deliver_notification(self, push: Dict[str, Any]) -> int:
		"""Send one notification to the configured targets; return how many accepted it."""
		services, persistent = self._notification_targets()
		delivered = 0
		service_data: Dict[str, Any] = {
			"title": push["title"],
			"message": push["message"],
			"data": {
				"url": push["url"],  # iOS companion app
				"clickAction": push["url"],  # Android companion app
				"tag": push["tag"],
				"group": "InfoMentor",
				"channel": "InfoMentor",  # Android: sound/importance adjustable per channel
			},
		}
		for svc in services:
			domain, _, service = svc.partition(".") if "." in svc else ("notify", "", svc)
			try:
				await self.hass.services.async_call(domain, service, service_data, blocking=True)
				delivered += 1
				_LOGGER.debug("Sent %s via %s.%s", push["tag"], domain, service)
			except Exception as err:
				_LOGGER.warning("Failed to send InfoMentor notification via %s.%s: %s", domain, service, err)
		if persistent:
			persistent_notification.async_create(
				self.hass,
				f"{push['message']}\n\n[Open in InfoMentor]({push['url']})",
				title=push["title"],
				notification_id=push["tag"],
			)
			delivered += 1
		return delivered

	async def async_send_test_notification(self) -> None:
		"""Send the latest InfoMentor notification (or a placeholder) to the configured targets."""
		services, persistent = self._notification_targets()
		if not services and not persistent:
			raise HomeAssistantError(
				"No notification targets configured: open InfoMentor → Configure and pick notify services"
			)
		latest = self._notifications[0] if self._notifications else None
		if latest and self.client:
			async with self._api_lock:
				push = await self._describe_notification(latest)
		else:
			push = {
				"title": "InfoMentor",
				"message": "Test notification — InfoMentor notifications will arrive like this.",
				"url": "https://hub.infomentor.se/#/",
			}
		push = {**push, "title": f"(Test) {push['title']}", "tag": "infomentor_test"}
		if await self._deliver_notification(push) == 0:
			raise HomeAssistantError("The test notification could not be delivered; check the log for details")

	@property
	def notifications(self) -> List[InfoMentorNotification]:
		"""Return the latest fetched notifications."""
		return list(self._notifications)

	async def _save_data_to_storage(self, data: Dict[str, Any], complete_schedule: bool) -> None:
		"""Save current data to persistent storage."""
		try:
			# Extract pupil names from pupils_info
			pupil_names = {}
			for pupil_id, info in self.pupils_info.items():
				if info.name:
					pupil_names[pupil_id] = info.name
			
			from datetime import timezone
			now_utc = datetime.now(timezone.utc)
			
			await self.storage.async_save(
				pupil_data=data,
				pupil_ids=self.pupil_ids,
				pupil_names=pupil_names,
				last_update=now_utc,
				auth_success=self.client and self.client.auth.authenticated,
				complete_schedule=complete_schedule,
			)
			if complete_schedule:
				self._last_successful_update = now_utc
			else:
				_LOGGER.debug("Partial data saved; freshness timestamp unchanged until all schedules are refreshed")
			self._using_cached_data = False
			_LOGGER.debug("Saved data to persistent storage")
		except Exception as e:
			_LOGGER.warning(f"Error saving data to storage: {e}")
	
	@callback
	def async_start_timers(self) -> None:
		"""Start notification polling and the midnight rollover of today/tomorrow sensors."""
		self._unsub_timers.append(
			async_track_time_interval(
				self.hass,
				self._async_notification_tick,
				timedelta(minutes=NOTIFICATION_CHECK_INTERVAL_MINUTES),
			)
		)
		self._unsub_timers.append(
			async_track_time_change(self.hass, self._async_midnight_rollover, hour=0, minute=0, second=5)
		)

	@callback
	def _async_midnight_rollover(self, _now: datetime) -> None:
		"""Re-evaluate today/tomorrow sensors once the date changes."""
		self._update_schedule_cache()
		self.async_update_listeners()

	async def _async_notification_tick(self, _now: Optional[datetime] = None) -> None:
		"""Poll notifications between the (much less frequent) data refreshes."""
		if not self.client or not self.client.authenticated or self._api_lock.locked():
			return
		if self._notification_retry_at and dt_util.utcnow() < self._notification_retry_at:
			return
		async with self._api_lock:
			if not self.client:
				return
			before = [(n.id, n.state) for n in self._notifications]
			ok = await self._poll_notifications_locked()
		if ok:
			self._notification_failures = 0
			self._notification_retry_at = None
		else:
			self._notification_failures += 1
			delay = min(
				timedelta(minutes=NOTIFICATION_CHECK_INTERVAL_MINUTES) * 2 ** self._notification_failures,
				NOTIFICATION_MAX_BACKOFF,
			)
			self._notification_retry_at = dt_util.utcnow() + delay
			_LOGGER.debug("Notification poll failed %d time(s); next attempt in %s", self._notification_failures, delay)
		if before != [(n.id, n.state) for n in self._notifications]:
			self.async_update_listeners()

	async def _poll_notifications_locked(self) -> bool:
		"""Re-login if needed and fetch notifications; caller holds ``_api_lock``."""
		if self._notification_session_stale or self._client_session_age() > NOTIFICATION_SESSION_MAX_AGE:
			if self._should_backoff():
				return False
			try:
				await self.client.login(self.username, self.password)
			except Exception as err:
				self._record_auth_failure()
				_LOGGER.warning("Re-login for notification polling failed: %s", err)
				return False
		try:
			await self._check_notifications(force=True)
		except Exception as err:
			_LOGGER.debug("Notification poll failed: %s", err)
			return False
		return not self._notification_session_stale

	def _client_session_age(self) -> timedelta:
		"""How long ago the current client last logged in (very large if unknown)."""
		auth = self.client.auth if self.client else None
		last_auth = getattr(auth, "_last_auth_time", None) if auth else None
		if not last_auth:
			return timedelta.max
		import time as _time
		return timedelta(seconds=max(0.0, _time.time() - last_auth))

	async def async_shutdown(self) -> None:
		"""Shutdown the coordinator and clean up resources."""
		while self._unsub_timers:
			self._unsub_timers.pop()()
		# Cancels the scheduled refresh; without this an unloaded/reloaded entry keeps polling
		await super().async_shutdown()
		if self.client:
			try:
				await self.client.__aexit__(None, None, None)
			except Exception as err:
				_LOGGER.warning(f"Error during client shutdown: {err}")
			finally:
				self.client = None
		# The session comes from async_create_clientsession; HA detaches it on unload/stop
		self._session = None
			
	async def async_refresh_pupil_data(self, pupil_id: str) -> None:
		"""Refresh data for a specific pupil."""
		if pupil_id not in self.pupil_ids:
			_LOGGER.warning(f"Pupil {pupil_id} not found in available pupils")
			return
			
		try:
			async with self._api_lock:
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
		schedule = self.get_pupil_schedule(pupil_id)
		today = _local_now().date()
		
		for day in schedule:
			if day.date.date() == today:
				return day
		return None
		
	def get_tomorrow_schedule(self, pupil_id: str) -> Optional[ScheduleDay]:
		"""Get tomorrow's schedule for a pupil."""
		schedule = self.get_pupil_schedule(pupil_id)
		tomorrow = _local_now().date() + timedelta(days=1)
		
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
		from datetime import timezone
		backoff_end = self._last_auth_failure + timedelta(minutes=AUTH_BACKOFF_MINUTES)
		now_utc = datetime.now(timezone.utc)
		return now_utc < backoff_end
		
	def _get_backoff_time(self) -> int:
		"""Get remaining backoff time in seconds."""
		if not self._last_auth_failure:
			return 0
			
		from datetime import timezone
		backoff_end = self._last_auth_failure + timedelta(minutes=AUTH_BACKOFF_MINUTES)
		now_utc = datetime.now(timezone.utc)
		remaining = backoff_end - now_utc
		return max(0, int(remaining.total_seconds()))
		
	def _record_auth_failure(self) -> None:
		"""Record an authentication failure."""
		from datetime import timezone
		self._auth_failure_count += 1
		self._last_auth_failure = datetime.now(timezone.utc)
		_LOGGER.warning(f"Authentication failure #{self._auth_failure_count} recorded")
		
	# Simplified retry scheduling logic
	def _calculate_next_update_interval(self) -> timedelta:
		"""Calculate the next update interval based on current state."""
		# If cached data is stale, move into hourly retry mode with jitter
		if self._is_data_stale():
			interval = self._hourly_retry_interval_with_jitter()
			if not self._stale_retry_logged:
				self._stale_retry_logged = True
				if self._last_successful_update:
					_LOGGER.warning(f"Last successful InfoMentor update is older than 24 hours ({self._last_successful_update}); retrying hourly at offset +{self._stale_retry_jitter_minutes} minutes")
				else:
					_LOGGER.warning("No successful InfoMentor data yet; retrying hourly until we fetch fresh data")
			return interval
		else:
			self._stale_retry_logged = False
			self._stale_retry_jitter_minutes = None
		
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
	
	def _schedule_refresh_after_cached_startup(self) -> None:
		"""After starting from cache, refresh when the cached data would normally be due."""
		interval = timedelta(minutes=RETRY_INTERVAL_MINUTES_FAST)
		if self._last_successful_update:
			from datetime import timezone
			last_update = self._last_successful_update
			if last_update.tzinfo is None:
				last_update = last_update.replace(tzinfo=timezone.utc)
			remaining = DEFAULT_UPDATE_INTERVAL - (datetime.now(timezone.utc) - last_update)
			interval = max(interval, remaining)
		_LOGGER.info(f"Started from cached data; next InfoMentor refresh in {interval}")
		self.update_interval = interval

	def _is_data_stale(self, max_age_hours: int = 24) -> bool:
		"""Return True if the last successful update is older than max_age_hours."""
		from datetime import timezone
		
		if not self._last_successful_update:
			return True
		
		last_update = self._last_successful_update
		if last_update.tzinfo is None:
			last_update = last_update.replace(tzinfo=timezone.utc)
		
		now_utc = datetime.now(timezone.utc)
		return (now_utc - last_update) > timedelta(hours=max_age_hours)
	
	def _hourly_retry_interval_with_jitter(self) -> timedelta:
		"""Return roughly-hourly interval but offset from :00 to avoid clashes."""
		jitter_minutes = random.randint(3, 17)
		self._stale_retry_jitter_minutes = jitter_minutes
		total_seconds = 3600 + jitter_minutes * 60
		return timedelta(seconds=total_seconds)
		
	def _update_retry_tracking(self, schedule_complete: bool) -> None:
		"""Update retry tracking based on whether all pupils have fresh schedules."""
		now = _local_now()
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
		if schedule_complete:
			self._today_data_available = True
			self._last_successful_today_data_fetch = now
			# Reset failure counts on success
			self._auth_failure_count = 0
			self._last_auth_failure = None
			self._daily_retry_count = 0  # Reset so we go back to standard interval
			self._stale_retry_logged = False
			self._stale_retry_jitter_minutes = None
			_LOGGER.info("Complete schedule retrieved for all pupils, resetting to standard update interval")
		else:
			self._today_data_available = False
			_LOGGER.warning(f"Incomplete schedule detected, will retry (attempt #{self._daily_retry_count})")
		
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
			
		now = _local_now()
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
			
		now = _local_now()
		
		# If it's been more than 23 hours since last update, it's time to refresh
		if (now - self._last_schedule_cache_update).total_seconds() > 23 * 3600:
			return True
			
		# If we've crossed midnight since last update
		if now.date() != self._last_schedule_cache_update.date():
			return True
			
		return False
	
	def get_cached_today_schedule(self, pupil_id: str) -> Optional[ScheduleDay]:
		"""Get cached today's schedule, falling back to live data if cache miss."""
		# Try cache first (ignore it once the date has rolled over)
		if pupil_id in self._cached_today_schedule:
			cached = self._cached_today_schedule[pupil_id]
			if cached and cached.date.date() == _local_now().date():
				_LOGGER.debug(f"Using cached today schedule for pupil {pupil_id}")
				return cached
		
		# Fall back to live data
		return self.get_today_schedule(pupil_id)
	
	def get_cached_tomorrow_schedule(self, pupil_id: str) -> Optional[ScheduleDay]:
		"""Get cached tomorrow's schedule, falling back to live data if cache miss."""
		# Try cache first (ignore it once the date has rolled over)
		if pupil_id in self._cached_tomorrow_schedule:
			cached = self._cached_tomorrow_schedule[pupil_id]
			if cached and cached.date.date() == _local_now().date() + timedelta(days=1):
				_LOGGER.debug(f"Using cached tomorrow schedule for pupil {pupil_id}")
				return cached
		
		# Fall back to live data
		return self.get_tomorrow_schedule(pupil_id)
	
	def schedule_is_complete(self) -> bool:
		"""Return True when every pupil has a fresh schedule."""
		return self._last_schedule_complete
	
	def missing_schedule_pupils(self) -> List[str]:
		"""List pupils with no schedule data in the latest refresh."""
		return list(self._missing_schedule_pupils)
	
	def cached_schedule_pupils(self) -> List[str]:
		"""List pupils whose schedules fell back to cached data."""
		return list(self._stale_schedule_pupils)

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

	def _record_diag(self, level: str, message: str, **fields: Any) -> None:
		"""Append an event to the in-memory diagnostic ring buffer.

		These events are exposed via the "InfoMentor Diagnostic Log" sensor
		attributes and the HA diagnostics download so users can see what's
		happening without needing shell access to the VM running HA.
		"""
		from datetime import timezone
		event: Dict[str, Any] = {
			"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
			"level": level,
			"message": message,
		}
		if fields:
			event["data"] = fields
		self._diag_events.append(event)
		if len(self._diag_events) > self._diag_events_max:
			del self._diag_events[: len(self._diag_events) - self._diag_events_max]

	@property
	def diagnostic_events(self) -> List[Dict[str, Any]]:
		"""Return a copy of the recent diagnostic events ring buffer."""
		return list(self._diag_events)

	async def async_diagnostic_poke(self, *, clear_cache: bool = False) -> None:
		"""Manual trigger from UI: refresh session, bypass throttles, then refresh data.

		Use when the integration is stuck on hourly retries, notifications stay empty,
		or you see HTTP 500 / HTML timetable responses and want an immediate retry.
		"""
		_LOGGER.warning(
			"InfoMentor diagnostics poke started (clear_cache=%s, user=%s)",
			clear_cache,
			self.username,
		)
		self._record_diag("info", "Diagnostics poke started", clear_cache=clear_cache)

		self._last_notification_check = None
		self._auth_failure_count = 0
		self._last_auth_failure = None
		self._daily_retry_count = 0
		self._today_data_available = False

		relogin_ok = False
		try:
			if self.client and getattr(self.client, "auth", None):
				async with self._api_lock:
					await self.client.login(self.username, self.password)
					self.pupil_ids = list(await self.client.get_pupil_ids())
				relogin_ok = True
				_LOGGER.warning(
					"Diagnostics poke: session refresh OK, pupils=%s",
					self.pupil_ids,
				)
				self._record_diag("info", "Session refresh OK", pupils=self.pupil_ids)
			else:
				_LOGGER.warning(
					"Diagnostics poke: no active client yet; full setup will run on refresh",
				)
				self._record_diag("warning", "No active client; full setup deferred")
		except Exception as err:
			_LOGGER.warning(
				"Diagnostics poke: re-login failed (%s); will create a new client on refresh",
				err,
			)
			self._record_diag("error", "Re-login failed", error=str(err))
			if self.client:
				try:
					await self.client.__aexit__(None, None, None)
				except Exception:
					pass
				self.client = None

		n_cookies = 0
		cookies_by_domain: dict[str, int] = {}
		if self._session and getattr(self._session, "cookie_jar", None):
			for cookie in self._session.cookie_jar:
				n_cookies += 1
				try:
					dom = cookie["domain"] or "?"
				except Exception:
					dom = "?"
				cookies_by_domain[dom] = cookies_by_domain.get(dom, 0) + 1
		_LOGGER.warning(
			"Diagnostics poke: aiohttp cookies=%d (by domain: %s), relogin_ok=%s",
			n_cookies,
			", ".join(f"{d}={c}" for d, c in sorted(cookies_by_domain.items())) or "none",
			relogin_ok,
		)
		self._record_diag(
			"info",
			"Cookie state",
			total=n_cookies,
			by_domain=cookies_by_domain,
			relogin_ok=relogin_ok,
		)

		if relogin_ok and self.client:
			try:
				async with self._api_lock:
					warmup_ok = await self.client.warmup_hub_session()
				_LOGGER.warning("Diagnostics poke: hub warmup ok=%s", warmup_ok)
				self._record_diag("info", "Hub warmup", ok=warmup_ok)
			except Exception as err:
				_LOGGER.warning("Diagnostics poke: hub warmup raised: %s", err)
				self._record_diag("error", "Hub warmup raised", error=str(err))

		if clear_cache:
			self._cached_today_schedule.clear()
			self._cached_tomorrow_schedule.clear()
			self._last_schedule_cache_update = None
			_LOGGER.warning("Diagnostics poke: cleared in-memory schedule cache")

		await self.async_refresh()

		# The cached-data path inside `_async_update_data` fires
		# `_background_notification_check()` as a detached task, so the buffer
		# may still be empty when async_refresh() returns. Run the check here
		# synchronously so the final log line reports the real number and new
		# notifications are pushed immediately.
		try:
			async with self._api_lock:
				await self._check_notifications(force=True)
		except Exception as err:
			_LOGGER.warning("Diagnostics poke: synchronous notification check failed: %s", err)
			self._record_diag("error", "Notification check failed", error=str(err))

		_LOGGER.warning(
			"Diagnostics poke finished: notification_buffer_len=%d",
			len(self._notifications),
		)
		self._record_diag(
			"info",
			"Diagnostics poke finished",
			notifications=len(self._notifications),
		)
		self.async_update_listeners()

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

	async def _background_auth_check(self) -> None:
		"""Perform a background authentication check without blocking updates.
		
		This verifies that authentication still works, but if it fails,
		we just log the error and continue using cached data.
		"""
		from datetime import timezone
		
		try:
			_LOGGER.debug("Starting background authentication check")
			self._last_auth_check = datetime.now(timezone.utc)
			
			# Wait a bit to avoid interfering with startup
			await asyncio.sleep(30)
			
			async with self._api_lock:
				await self._background_auth_check_locked()
				
			# Picks up notifications as soon as the session is ready
			await self._async_notification_tick()
			
		except Exception as e:
			_LOGGER.warning(f"Background authentication check failed (will continue using cached data): {e}")
	
	async def _background_auth_check_locked(self) -> None:
		"""Body of the background auth check; caller holds ``_api_lock``."""
		try:
			# Try to setup/verify client authentication
			if not self.client or not hasattr(self.client, 'auth') or not self.client.auth.authenticated:
				_LOGGER.debug("Background auth check: Setting up client")
				await self._setup_client()
				
				# Verify we got pupil IDs
				if self.pupil_ids:
					_LOGGER.info(f"Background authentication check successful - credentials verified, {len(self.pupil_ids)} pupils found")
				else:
					_LOGGER.warning("Background authentication check: Auth succeeded but no pupil IDs - using cached data")
					return
			else:
				# Just verify existing auth is still valid
				if self.client.auth.is_auth_likely_expired():
					_LOGGER.debug("Background auth check: Re-authenticating")
					await self.client.login(self.username, self.password)
					
					# Verify pupil IDs after re-auth
					if not self.pupil_ids:
						_LOGGER.debug("Background auth check: Re-fetching pupil IDs")
						await self._setup_client()
					
					if self.pupil_ids:
						_LOGGER.info(f"Background authentication check successful - credentials refreshed, {len(self.pupil_ids)} pupils confirmed")
					else:
						_LOGGER.warning("Background authentication check: Re-auth succeeded but no pupil IDs - using cached data")
						return
				else:
					_LOGGER.debug("Background authentication check: Auth still valid")
			
			# Reset auth failure count on successful background check
			self._auth_failure_count = 0
			self._last_auth_failure = None
			
		except Exception as e:
			_LOGGER.warning(f"Background authentication check failed (will continue using cached data): {e}")
			# Don't raise - this is a background check, failures are non-critical
	
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
