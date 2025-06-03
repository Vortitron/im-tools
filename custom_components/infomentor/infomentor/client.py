"""Main client for InfoMentor API."""

import json
import logging
from datetime import datetime, time, timedelta
from typing import List, Optional, Dict, Any

import aiohttp

from .auth import InfoMentorAuth, HUB_BASE_URL, DEFAULT_HEADERS
from .models import (
	NewsItem, TimelineEntry, PupilInfo, Assignment, AttendanceEntry,
	TimetableEntry, TimeRegistrationEntry, ScheduleDay
)
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

	async def get_timetable(self, pupil_id: Optional[str] = None, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> List[TimetableEntry]:
		"""Get timetable entries for a pupil (school children).
		
		Args:
			pupil_id: Optional pupil ID. If provided, switches to that pupil first.
			start_date: Start date for timetable (default: today)
			end_date: End date for timetable (default: one week from start_date)
			
		Returns:
			List of TimetableEntry objects
		"""
		self._ensure_authenticated()
		
		if pupil_id:
			switch_result = await self.switch_pupil(pupil_id)
			if not switch_result:
				_LOGGER.warning(f"Failed to switch to pupil {pupil_id} for timetable")
				return []
			_LOGGER.debug(f"Successfully switched to pupil {pupil_id} for timetable")
		
		# Set default dates if not provided
		if not start_date:
			start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
		if not end_date:
			end_date = start_date + timedelta(weeks=1)
			
		_LOGGER.debug(f"Getting timetable data for pupil {pupil_id} from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
		
		# Use the correct timetable endpoint instead of calendar
		return await self._get_timetable_with_retry(pupil_id, start_date, end_date)
	
	async def _get_timetable_with_retry(self, pupil_id: Optional[str], start_date: datetime, end_date: datetime, retry_count: int = 0) -> List[TimetableEntry]:
		"""Get timetable with automatic retry on authentication failure."""
		max_retries = 1  # Only retry once to avoid infinite loops
		
		try:
			timetable_url = f"{HUB_BASE_URL}/timetable/timetable/gettimetablelist"
			headers = DEFAULT_HEADERS.copy()
			headers.update({
				"Accept": "application/json, text/javascript, */*; q=0.01",
				"X-Requested-With": "XMLHttpRequest",
			})
			
			# Build URL with query parameters
			params = {
				"startDate": start_date.strftime('%Y-%m-%d'),
				"endDate": end_date.strftime('%Y-%m-%d'),
			}
			
			_LOGGER.debug(f"Making timetable GET request to {timetable_url} (attempt {retry_count + 1})")
			_LOGGER.debug(f"Request params: {params}")
			
			async with self._session.get(timetable_url, headers=headers, params=params) as resp:
				if resp.status == 200:
					data = await resp.json()
					return self._parse_timetable_from_api(data, pupil_id, start_date, end_date)
				elif resp.status in [401, 403]:
					# Authentication related errors
					_LOGGER.warning(f"Authentication error (HTTP {resp.status}) - session may have expired")
					response_text = await resp.text()
					
					if retry_count < max_retries and "HandleUnauthorizedRequest" in response_text:
						_LOGGER.info("Attempting to re-authenticate and retry...")
						await self._handle_authentication_failure()
						return await self._get_timetable_with_retry(pupil_id, start_date, end_date, retry_count + 1)
					
					_LOGGER.debug(f"Auth error response: {response_text[:200]}...")
					return []
				else:
					# Capture detailed error information
					response_headers = dict(resp.headers)
					try:
						response_text = await resp.text()
					except:
						response_text = "Could not read response body"
					
					_LOGGER.warning(f"Failed to get timetable entries: HTTP {resp.status}")
					_LOGGER.warning(f"Response headers: {response_headers}")
					_LOGGER.warning(f"Response body: {response_text}")
					
					# Check for session expiration in response body
					if retry_count < max_retries and "HandleUnauthorizedRequest" in response_text:
						_LOGGER.info("Detected session expiration in response body - attempting to re-authenticate...")
						await self._handle_authentication_failure()
						return await self._get_timetable_with_retry(pupil_id, start_date, end_date, retry_count + 1)
					
					# If GET fails with "Invalid Verb" or similar, try POST as fallback
					if "invalid verb" in response_text.lower() or "bad request" in response_text.lower():
						_LOGGER.info("GET request failed with verb error, trying POST as fallback...")
						return await self._get_timetable_post_fallback(pupil_id, start_date, end_date)
					
					return []
					
		except Exception as e:
			_LOGGER.warning(f"Failed to get timetable entries: {e}")
			import traceback
			_LOGGER.warning(f"Exception traceback: {traceback.format_exc()}")
		
		# If timetable API fails, return empty list
		_LOGGER.debug("Timetable retrieval failed, returning empty schedule")
		return []
	
	async def _handle_authentication_failure(self) -> None:
		"""Handle authentication failure by re-authenticating."""
		if not self.auth:
			_LOGGER.error("Cannot re-authenticate - no auth handler available")
			return
		
		try:
			_LOGGER.info("Re-authenticating due to session expiration...")
			
			# Get current credentials (assuming they're stored in auth)
			if hasattr(self.auth, '_username') and hasattr(self.auth, '_password'):
				username = self.auth._username
				password = self.auth._password
			else:
				_LOGGER.error("Cannot re-authenticate - credentials not available")
				return
			
			# Reset authentication state
			self.auth.authenticated = False
			self.authenticated = False
			
			# Re-authenticate
			success = await self.auth.login(username, password)
			if success:
				self.authenticated = True
				_LOGGER.info("Re-authentication successful")
			else:
				_LOGGER.error("Re-authentication failed")
				
		except Exception as e:
			_LOGGER.error(f"Re-authentication error: {e}")
			import traceback
			_LOGGER.error(f"Re-authentication traceback: {traceback.format_exc()}")

	async def get_time_registration(self, pupil_id: Optional[str] = None, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> List[TimeRegistrationEntry]:
		"""Get time registration entries for a pupil (preschool/fritids).
		
		Args:
			pupil_id: Optional pupil ID. If provided, switches to that pupil first.
			start_date: Start date for registration (default: today)
			end_date: End date for registration (default: one week from start_date)
			
		Returns:
			List of TimeRegistrationEntry objects
		"""
		self._ensure_authenticated()
		
		# Additional authentication validation
		if not self.auth or not self.auth.authenticated:
			_LOGGER.warning("Authentication check failed for time registration - auth object not properly authenticated")
			return []
		
		if not self.auth.pupil_ids:
			_LOGGER.warning("No pupil IDs available for time registration - may indicate authentication issues")
			return []
		
		if pupil_id:
			switch_result = await self.switch_pupil(pupil_id)
			if not switch_result:
				_LOGGER.warning(f"Failed to switch to pupil {pupil_id} for time registration")
				return []
			_LOGGER.debug(f"Successfully switched to pupil {pupil_id} for time registration")
		else:
			_LOGGER.debug(f"No pupil_id provided, using current session context")
			
		# Set default dates if not provided
		if not start_date:
			start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
		if not end_date:
			end_date = start_date + timedelta(weeks=1)
		
		_LOGGER.debug(f"Getting time registration data for pupil {pupil_id} from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
		
		# Try GET request first for time registration API (more reliable)
		try:
			time_reg_url = f"{HUB_BASE_URL}/TimeRegistration/TimeRegistration/GetTimeRegistrations/"
			headers = DEFAULT_HEADERS.copy()
			headers.update({
				"Accept": "application/json, text/javascript, */*; q=0.01",
				"X-Requested-With": "XMLHttpRequest",
			})
			
			params = {
				"startDate": start_date.strftime('%Y-%m-%d'),
				"endDate": end_date.strftime('%Y-%m-%d'),
			}
			
			_LOGGER.debug(f"🔧 NEW VERSION: Making time registration GET request to {time_reg_url}")
			_LOGGER.debug(f"Request params: {params}")
			
			async with self._session.get(time_reg_url, headers=headers, params=params) as resp:
				if resp.status == 200:
					data = await resp.json()
					_LOGGER.debug(f"Got time registration data: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
					
					# Log the number of days returned to help diagnose pupil switching issues
					days = data.get('days', [])
					_LOGGER.info(f"Time registration API returned {len(days)} days for pupil {pupil_id}")
					
					# Log a sample of the data to help diagnose if pupils are getting identical data
					if days and len(days) > 0:
						sample_day = days[0]
						_LOGGER.debug(f"Sample day data for pupil {pupil_id}: date={sample_day.get('date')}, "
									f"startDateTime={sample_day.get('startDateTime')}, "
									f"endDateTime={sample_day.get('endDateTime')}, "
									f"timeRegistrationId={sample_day.get('timeRegistrationId')}")
					
					return self._parse_time_registration_from_api(data, pupil_id, start_date, end_date)
				elif resp.status in [401, 403]:
					_LOGGER.warning(f"Authentication error for time registration (HTTP {resp.status}) - session may have expired")
					response_text = await resp.text()
					
					# Check for session expiration and attempt re-authentication
					if "HandleUnauthorizedRequest" in response_text:
						_LOGGER.info("Attempting to re-authenticate for time registration and retry...")
						await self._handle_authentication_failure()
						# Retry once after re-authentication
						async with self._session.get(time_reg_url, headers=headers, params=params) as retry_resp:
							if retry_resp.status == 200:
								retry_data = await retry_resp.json()
								_LOGGER.info("Time registration retry after re-authentication succeeded")
								return self._parse_time_registration_from_api(retry_data, pupil_id, start_date, end_date)
					
					return []
		except Exception as e:
			_LOGGER.warning(f"Failed to get time registrations: {e}")
		
		# Try alternative time registration calendar data endpoint with GET first
		try:
			time_cal_url = f"{HUB_BASE_URL}/TimeRegistration/TimeRegistration/GetCalendarData/"
			headers = DEFAULT_HEADERS.copy()
			headers.update({
				"Accept": "application/json, text/javascript, */*; q=0.01",
				"X-Requested-With": "XMLHttpRequest",
			})
			
			params = {
				"startDate": start_date.strftime('%Y-%m-%d'),
				"endDate": end_date.strftime('%Y-%m-%d'),
			}
			
			async with self._session.get(time_cal_url, headers=headers, params=params) as resp:
				if resp.status == 200:
					data = await resp.json()
					_LOGGER.debug(f"Got time registration calendar data: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
					return self._parse_time_registration_calendar_from_api(data, pupil_id, start_date, end_date)
				elif resp.status in [401, 403]:
					_LOGGER.warning(f"Authentication error for time reg calendar (HTTP {resp.status}) - session may have expired")
					return []
				else:
					response_headers = dict(resp.headers)
					try:
						response_text = await resp.text()
					except:
						response_text = "Could not read response body"
					
					_LOGGER.warning(f"Failed to get time registration calendar data: HTTP {resp.status}")
					_LOGGER.warning(f"Time reg calendar response headers: {response_headers}")
					_LOGGER.warning(f"Time reg calendar response body: {response_text}")
					
					# If GET fails with "Invalid Verb", try POST fallback
					if "invalid verb" in response_text.lower() or "bad request" in response_text.lower():
						_LOGGER.info("Time reg calendar GET failed with verb error, trying POST fallback...")
						return await self._get_time_registration_post_fallback(pupil_id, start_date, end_date, time_cal_url)
					
		except Exception as e:
			_LOGGER.warning(f"Failed to get time registration calendar data: {e}")
		
		# If all methods fail, return empty list
		_LOGGER.warning("All time registration data retrieval methods failed")
		return []
	
	async def _get_time_registration_post_fallback(self, pupil_id: Optional[str], start_date: datetime, end_date: datetime, url: str) -> List[TimeRegistrationEntry]:
		"""Fallback method to try POST for time registration if GET fails."""
		try:
			headers = DEFAULT_HEADERS.copy()
			headers.update({
				"Accept": "application/json, text/javascript, */*; q=0.01",
				"X-Requested-With": "XMLHttpRequest",
				"Content-Type": "application/json; charset=UTF-8",
			})
			
			payload = {
				"startDate": start_date.strftime('%Y-%m-%d'),
				"endDate": end_date.strftime('%Y-%m-%d'),
			}
			
			_LOGGER.debug(f"Making fallback time registration POST request to {url}")
			
			async with self._session.post(url, headers=headers, json=payload) as resp:
				if resp.status == 200:
					data = await resp.json()
					_LOGGER.info("POST fallback succeeded for time registration")
					if "GetTimeRegistrations" in url:
						return self._parse_time_registration_from_api(data, pupil_id, start_date, end_date)
					else:
						return self._parse_time_registration_calendar_from_api(data, pupil_id, start_date, end_date)
				else:
					response_headers = dict(resp.headers)
					try:
						response_text = await resp.text()
					except:
						response_text = "Could not read response body"
					
					_LOGGER.warning(f"Time registration POST fallback failed: HTTP {resp.status}")
					_LOGGER.warning(f"Response headers: {response_headers}")
					_LOGGER.warning(f"Response body: {response_text}")
					
		except Exception as e:
			_LOGGER.warning(f"Time registration POST fallback exception: {e}")
		
		return []

	async def get_schedule(self, pupil_id: Optional[str] = None, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> List[ScheduleDay]:
		"""Get complete schedule for a pupil including both timetable and time registration.
		
		Args:
			pupil_id: Optional pupil ID. If provided, switches to that pupil first.
			start_date: Start date for schedule (default: today)
			end_date: End date for schedule (default: one week from start_date)
			
		Returns:
			List of ScheduleDay objects
		"""
		self._ensure_authenticated()
		
		if pupil_id:
			await self.switch_pupil(pupil_id)
			
		# Set default dates if not provided
		if not start_date:
			start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
		if not end_date:
			end_date = start_date + timedelta(weeks=1)
			
		# Get both timetable and time registration data
		# Pass None as pupil_id to avoid redundant switching since we already switched above
		timetable_entries = await self.get_timetable(None, start_date, end_date)
		time_registrations = await self.get_time_registration(None, start_date, end_date)
		
		# Group entries by date
		schedule_days = {}
		current_date = start_date
		
		# Initialize all days in the range
		while current_date <= end_date:
			day_key = current_date.strftime('%Y-%m-%d')
			schedule_days[day_key] = ScheduleDay(
				date=current_date,
				pupil_id=pupil_id or "unknown",
				timetable_entries=[],
				time_registrations=[]
			)
			current_date += timedelta(days=1)
			
		# Add timetable entries to their respective days
		for entry in timetable_entries:
			day_key = entry.date.strftime('%Y-%m-%d')
			if day_key in schedule_days:
				schedule_days[day_key].timetable_entries.append(entry)
				
		# Add time registration entries to their respective days
		for entry in time_registrations:
			day_key = entry.date.strftime('%Y-%m-%d')
			if day_key in schedule_days:
				schedule_days[day_key].time_registrations.append(entry)
				
		return list(schedule_days.values())
		
	async def get_pupil_info(self, pupil_id: str) -> Optional[PupilInfo]:
		"""Get information about a specific pupil.
		
		Args:
			pupil_id: ID of pupil
			
		Returns:
			PupilInfo object or None if not found
		"""
		self._ensure_authenticated()
		
		if pupil_id not in self.auth.pupil_ids:
			return None
			
		# Try to extract pupil name from hub page
		try:
			hub_url = f"{HUB_BASE_URL}/#/"
			headers = DEFAULT_HEADERS.copy()
			headers["Referer"] = f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true"
			
			async with self._session.get(hub_url, headers=headers) as resp:
				if resp.status == 200:
					text = await resp.text()
					name = self._extract_pupil_name_from_hub(text, pupil_id)
					return PupilInfo(id=pupil_id, name=name)
		except Exception as e:
			_LOGGER.warning(f"Failed to extract pupil name for {pupil_id}: {e}")
		
		# Fallback to basic info
		return PupilInfo(id=pupil_id)
		
	def _extract_pupil_name_from_hub(self, html_content: str, pupil_id: str) -> Optional[str]:
		"""Extract pupil name from hub page HTML.
		
		Args:
			html_content: HTML content from hub page
			pupil_id: Target pupil ID
			
		Returns:
			Pupil name if found, None otherwise
		"""
		import re
		import json
		
		# First try to extract from JSON structures (most reliable)
		name = self._extract_name_from_json_structure(html_content, pupil_id)
		if name:
			return name
		
		# Fallback to regex patterns
		patterns = [
			# Pattern 1: Switch pupil URL with name in JSON
			rf'"switchPupilUrl"\s*:\s*"[^"]*SwitchPupil/{re.escape(pupil_id)}"[^}}]*"name"\s*:\s*"([^"]+)"',
			# Pattern 2: Pupil switcher links
			rf'/Account/PupilSwitcher/SwitchPupil/{re.escape(pupil_id)}[^>]*>([^<]+)<',
			# Pattern 3: Data attributes
			rf'data-pupil-id="{re.escape(pupil_id)}"[^>]*>([^<]+)<',
			# Pattern 4: JSON with ID first then name
			rf'"id"\s*:\s*"{re.escape(pupil_id)}"[^}}]*"name"\s*:\s*"([^"]+)"',
			# Pattern 5: Select options
			rf'<option[^>]*value="{re.escape(pupil_id)}"[^>]*>([^<]+)</option>',
		]
		
		for pattern in patterns:
			matches = re.findall(pattern, html_content, re.IGNORECASE | re.DOTALL)
			for match in matches:
				name = match.strip() if isinstance(match, str) else match[0].strip()
				if self._is_valid_pupil_name(name):
					_LOGGER.debug(f"Extracted name '{name}' for pupil {pupil_id} using pattern")
					return name
		
		_LOGGER.debug(f"No name found for pupil {pupil_id}")
		return None
	
	def _extract_name_from_json_structure(self, html_content: str, pupil_id: str) -> Optional[str]:
		"""Extract pupil name from JSON structures in HTML.
		
		Args:
			html_content: HTML content containing JSON data
			pupil_id: Target pupil ID
			
		Returns:
			Pupil name if found, None otherwise
		"""
		import json
		import re
		
		try:
			# Look for JSON arrays containing pupil data
			json_patterns = [
				r'"pupils"\s*:\s*(\[[\s\S]*?\])',
				r'"children"\s*:\s*(\[[\s\S]*?\])',
				r'"students"\s*:\s*(\[[\s\S]*?\])',
				r'pupils\s*=\s*(\[[\s\S]*?\]);',
			]
			
			for pattern in json_patterns:
				matches = re.findall(pattern, html_content, re.IGNORECASE)
				for match in matches:
					try:
						pupils_data = json.loads(match)
						if isinstance(pupils_data, list):
							for pupil in pupils_data:
								if isinstance(pupil, dict):
									# Check if this pupil matches our target ID
									found_id = None
									
									# Check various ID fields
									if 'id' in pupil and str(pupil['id']) == pupil_id:
										found_id = pupil_id
									elif 'pupilId' in pupil and str(pupil['pupilId']) == pupil_id:
										found_id = pupil_id
									elif 'hybridMappingId' in pupil:
										# Handle format like "17637|2104025925|NEMANDI_SKOLI"
										mapping_id = str(pupil['hybridMappingId'])
										if pupil_id in mapping_id.split('|'):
											found_id = pupil_id
									
									if found_id and 'name' in pupil:
										name = str(pupil['name']).strip()
										if self._is_valid_pupil_name(name):
											_LOGGER.debug(f"Extracted name '{name}' for pupil {pupil_id} from JSON")
											return name
					except (json.JSONDecodeError, KeyError, ValueError) as e:
						_LOGGER.debug(f"Failed to parse JSON for name extraction: {e}")
						continue
			
			# Look for individual pupil objects by matching switch URLs
			switch_pattern = rf'"switchPupilUrl"\s*:\s*"[^"]*SwitchPupil/{re.escape(pupil_id)}"[^}}]*"name"\s*:\s*"([^"]+)"'
			matches = re.findall(switch_pattern, html_content, re.IGNORECASE | re.DOTALL)
			
			for match in matches:
				name = match.strip()
				if self._is_valid_pupil_name(name):
					_LOGGER.debug(f"Extracted name '{name}' for pupil {pupil_id} from switch pattern")
					return name
		
		except Exception as e:
			_LOGGER.debug(f"Error in JSON name extraction: {e}")
		
		return None
	
	def _is_valid_pupil_name(self, name: str) -> bool:
		"""Check if a name appears to be a valid pupil name.
		
		Args:
			name: Candidate name string
			
		Returns:
			True if name appears valid for a pupil
		"""
		import re
		
		if not name or len(name.strip()) < 2:
			return False
		
		name = name.strip()
		
		# Filter out obvious non-names
		invalid_patterns = [
			# Generic invalid content
			r'^\d+$',  # Just numbers
			r'^[^a-zA-ZÀ-ÿ]+$',  # No letters at all
			# Swedish error messages and system text
			r'vänligen kontrollera',
			r'kontaktuppgifter',
			r'preschool.*today',
			r'fritids.*today',
			r'has.*school',
			r'firsttimeinfo',
			r'föräldrarna',
			r'vårdnadshavare',
			# HTML/JavaScript artifacts
			r'<[^>]+>',
			r'function\s*\(',
			r'var\s+\w+',
			r'\.js$',
			r'\.css$',
			# Common parent indicators (make this more specific to avoid false positives)
			r'^andrew$',  # Only exact match to avoid filtering legitimate names containing "andrew"
		]
		
		for pattern in invalid_patterns:
			if re.search(pattern, name, re.IGNORECASE):
				_LOGGER.debug(f"Rejected name '{name}' due to pattern: {pattern}")
				return False
		
		# Check if this looks like a reasonable name (has letters and reasonable length)
		if not re.search(r'[a-zA-ZÀ-ÿ]', name):
			return False
		
		if len(name) > 100:  # Probably not a name if too long
			return False
		
		return True
		
	def _ensure_authenticated(self) -> None:
		"""Ensure client is authenticated."""
		if not self.authenticated or not self.auth:
			raise InfoMentorAPIError("Not authenticated. Call login() first.")
		
		# Log session state for debugging
		_LOGGER.debug(f"Authentication state: authenticated={self.authenticated}")
		_LOGGER.debug(f"Auth object: {self.auth is not None}")
		_LOGGER.debug(f"Pupil IDs: {len(self.auth.pupil_ids) if self.auth else 'None'}")
		if self._session and hasattr(self._session, 'cookie_jar'):
			cookie_count = len(self._session.cookie_jar)
			_LOGGER.debug(f"Session cookies: {cookie_count} cookies")
			# Log cookie domains for debugging
			domains = set()
			for cookie in self._session.cookie_jar:
				domains.add(cookie.get('domain', 'no-domain'))
			_LOGGER.debug(f"Cookie domains: {domains}")
		else:
			_LOGGER.debug("No session or cookie jar available")
	
	async def diagnose_authentication(self) -> Dict[str, Any]:
		"""Run authentication diagnostics for troubleshooting.
		
		Returns:
			Dictionary with diagnostic information
		"""
		if not self.auth:
			return {"error": "No authentication handler available"}
		
		return await self.auth.diagnose_auth_state()
			
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

	def _parse_timetable_from_api(self, data: Dict[str, Any], pupil_id: Optional[str], start_date: datetime, end_date: datetime) -> List[TimetableEntry]:
		"""Parse timetable data from API response.
		
		Args:
			data: Raw API response data
			pupil_id: Associated pupil ID
			start_date: Start date for parsing
			end_date: End date for parsing
			
		Returns:
			List of TimetableEntry objects
		"""
		timetable_entries = []
		
		try:
			_LOGGER.debug(f"Parsing timetable API data with keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
			
			# Look for entries in various possible keys
			entries = []
			for key in ['entries', 'events', 'items', 'data', 'timetableEntries', 'lessons']:
				if key in data and isinstance(data[key], list):
					entries = data[key]
					_LOGGER.debug(f"Found {len(entries)} entries in '{key}'")
					break
			
			if not entries:
				_LOGGER.warning("No timetable entries found in API response")
				return timetable_entries
			
			for entry in entries:
				try:
					# Extract common fields
					entry_id = str(entry.get('id', ''))
					title = entry.get('title', entry.get('name', entry.get('subject', '')))
					description = entry.get('description', entry.get('content', ''))
					
					# Parse date/time information
					start_date_parsed = self._parse_date(entry.get('startDate', entry.get('start', entry.get('date'))))
					end_date_parsed = self._parse_date(entry.get('endDate', entry.get('end')))
					start_time = self._parse_time(entry.get('startTime', entry.get('start')))
					end_time = self._parse_time(entry.get('endTime', entry.get('end')))
					
					# Extract additional fields
					subject = entry.get('subject', entry.get('course', title))
					teacher = entry.get('teacher', entry.get('instructor', entry.get('staff', '')))
					room = entry.get('room', entry.get('location', entry.get('classroom', '')))
					entry_type = entry.get('type', entry.get('entryType', entry.get('lessonType', 'lesson')))
					
					# Create timetable entry
					timetable_entry = TimetableEntry(
						id=entry_id,
						title=title,
						description=description,
						date=start_date_parsed or datetime.now(),
						start_time=start_time,
						end_time=end_time,
						subject=subject,
						teacher=teacher,
						room=room,
						entry_type=entry_type,
						pupil_id=pupil_id
					)
					
					timetable_entries.append(timetable_entry)
					_LOGGER.debug(f"Parsed timetable entry: {title} on {start_date_parsed}")
					
				except Exception as e:
					_LOGGER.warning(f"Failed to parse timetable entry: {e}")
					continue
			
			_LOGGER.info(f"Successfully parsed {len(timetable_entries)} timetable entries")
			
		except Exception as e:
			_LOGGER.error(f"Failed to parse timetable API response: {e}")
			
		return timetable_entries

	def _parse_time_registration_from_api(self, data: Dict[str, Any], pupil_id: Optional[str], start_date: datetime, end_date: datetime) -> List[TimeRegistrationEntry]:
		"""Parse time registration data from API response.
		
		Args:
			data: Raw API response data with 'days' array
			pupil_id: Associated pupil ID
			start_date: Start date for parsing
			end_date: End date for parsing
			
		Returns:
			List of TimeRegistrationEntry objects
		"""
		time_registrations = []
		
		try:
			_LOGGER.debug(f"Parsing time registration data with keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
			
			# The time registration API returns data with a 'days' array
			days = data.get('days', [])
			if not days:
				_LOGGER.warning("No time registrations found in API response")
				return time_registrations
			
			_LOGGER.debug(f"Found {len(days)} time registration days to parse")
			
			for day in days:
				try:
					# Extract fields from actual InfoMentor structure
					reg_id = str(day.get('timeRegistrationId', ''))
					
					# Parse date information
					date_str = day.get('date')
					reg_date = self._parse_date(date_str) if date_str else datetime.now()
					
					# Parse time information
					start_datetime_str = day.get('startDateTime')
					end_datetime_str = day.get('endDateTime')
					
					start_time = None
					end_time = None
					
					if start_datetime_str:
						start_datetime = self._parse_date(start_datetime_str)
						start_time = start_datetime.time() if start_datetime else None
					
					if end_datetime_str:
						end_datetime = self._parse_date(end_datetime_str)
						end_time = end_datetime.time() if end_datetime else None
					
					# Extract additional fields
					on_leave = day.get('onLeave', False)
					is_locked = day.get('isLocked', False)
					is_school_closed = day.get('isSchoolClosed', False)
					can_edit = day.get('canEdit', True)
					school_closed_reason = day.get('schoolClosedReason', '')
					
					# Determine status
					status = "scheduled"
					if is_school_closed:
						status = "school_closed"
					elif on_leave:
						status = "on_leave"
					elif is_locked and not start_time and not end_time:
						status = "not_scheduled"  # Locked with no times = not scheduled
					elif is_locked:
						status = "locked"
					elif not start_time or not end_time:
						status = "pending"  # Scheduled but times not set yet
					
					# Create time registration entry for any scheduled activity
					# This includes entries without specific times (pending/planned activities)
					# but excludes only truly inactive days (school closed, explicit not scheduled)
					should_include = (
						not (is_school_closed and not start_time and not end_time) and  # Skip only school closed days with no times
						status not in ["not_scheduled"] and  # Skip explicitly not scheduled
						(start_time or end_time or status in ["pending", "locked", "on_leave"])  # Include if has times OR is a planned activity
					)
					
					if should_include:
						time_reg_entry = TimeRegistrationEntry(
							id=reg_id,
							date=reg_date,
							start_time=start_time,
							end_time=end_time,
							status=status,
							comment=school_closed_reason if school_closed_reason else None,
							is_locked=is_locked,
							is_school_closed=is_school_closed,
							on_leave=on_leave,
							can_edit=can_edit,
							school_closed_reason=school_closed_reason,
							pupil_id=pupil_id
						)
						
						time_registrations.append(time_reg_entry)
						_LOGGER.debug(f"Parsed time registration: {reg_date.strftime('%Y-%m-%d')} {start_time or 'TBD'}-{end_time or 'TBD'} [{status}]")
					else:
						_LOGGER.debug(f"Skipped time registration: {reg_date.strftime('%Y-%m-%d')} [{status}] - truly inactive day")
					
				except Exception as e:
					_LOGGER.warning(f"Failed to parse time registration day: {e}")
					_LOGGER.debug(f"Day data: {day}")
					continue
			
			_LOGGER.info(f"Successfully parsed {len(time_registrations)} time registration entries")
			
		except Exception as e:
			_LOGGER.error(f"Failed to parse time registration data: {e}")
			
		return time_registrations

	def _parse_calendar_entries_as_timetable(self, data: Dict[str, Any], pupil_id: Optional[str], start_date: datetime, end_date: datetime) -> List[TimetableEntry]:
		"""Parse calendar entries as timetable data.
		
		Args:
			data: Calendar entries response data
			pupil_id: Associated pupil ID
			start_date: Start date for parsing
			end_date: End date for parsing
			
		Returns:
			List of TimetableEntry objects
		"""
		timetable_entries = []
		
		try:
			_LOGGER.debug(f"Parsing calendar entries with keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
			
			# Look for entries in various possible keys
			entries = []
			for key in ['entries', 'events', 'items', 'data', 'calendarEntries', 'calendar']:
				if key in data and isinstance(data[key], list):
					entries = data[key]
					_LOGGER.debug(f"Found {len(entries)} entries in '{key}'")
					break
			
			if not entries:
				_LOGGER.warning("No calendar entries found in API response")
				return timetable_entries
			
			_LOGGER.debug(f"Processing {len(entries)} calendar entries...")
			
			for entry in entries:
				try:
					# Extract common fields
					entry_id = str(entry.get('id', ''))
					title = entry.get('title', entry.get('name', ''))
					description = entry.get('description', entry.get('content', ''))
					calendar_entry_type_id = entry.get('calendarEntryTypeId')
					
					_LOGGER.debug(f"Processing entry: '{title}' (type: {calendar_entry_type_id})")
					
					# Skip known holiday types
					if calendar_entry_type_id == 13:  # Holiday type
						_LOGGER.debug(f"Skipping holiday entry (type 13): {title}")
						continue
					
					# Skip entries that look like holidays based on keywords
					holiday_keywords = ['lovdag', 'röd dag', 'helgdag', 'semester', 'lov', 'holiday', 'vacation']
					if any(keyword in title.lower() for keyword in holiday_keywords):
						_LOGGER.debug(f"Skipping holiday-like entry: {title}")
						continue
					
					# Parse date information
					start_date_str = entry.get('startDate')
					start_date_full = entry.get('startDateFull')
					end_date_str = entry.get('endDate')
					
					# Use startDateFull if available, otherwise startDate
					date_to_parse = start_date_full or start_date_str
					entry_date = self._parse_date(date_to_parse) if date_to_parse else datetime.now()
					
					# Parse time information
					start_time = self._parse_time(entry.get('startTime'))
					end_time = self._parse_time(entry.get('endTime'))
					is_all_day = entry.get('isAllDayEvent', False)
					
					# Extract additional fields
					subjects = entry.get('subjects', [])
					courses = entry.get('courses', [])
					
					# Determine subject from available data
					subject = ""
					if subjects:
						subject = subjects[0] if isinstance(subjects, list) else str(subjects)
					elif courses:
						subject = courses[0] if isinstance(courses, list) else str(courses)
					else:
						# Use title as subject as a fallback
						subject = title
					
					# More lenient check for actual lessons
					# Accept entries that have:
					# - A meaningful title/subject
					# - Either specific times OR all-day events that look educational
					is_potential_lesson = (
						subject and 
						len(subject.strip()) > 0 and 
						not subject.lower() in ['', 'none', 'null'] and
						# Accept both timed and all-day events
						(start_time and end_time) or is_all_day
					)
					
					if is_potential_lesson:
						timetable_entry = TimetableEntry(
							id=entry_id,
							title=title,
							date=entry_date,
							subject=subject,
							start_time=start_time,
							end_time=end_time,
							description=description,
							entry_type=f"calendar_type_{calendar_entry_type_id}" if calendar_entry_type_id else "calendar",
							is_all_day=is_all_day,
							pupil_id=pupil_id
						)
						
						timetable_entries.append(timetable_entry)
						_LOGGER.debug(f"✅ Parsed calendar entry as lesson: {title} on {entry_date.strftime('%Y-%m-%d')} ({start_time}-{end_time})")
					else:
						_LOGGER.debug(f"⏭️ Skipped entry - not a lesson: '{title}' (subject: '{subject}', times: {start_time}-{end_time}, all_day: {is_all_day})")
					
				except Exception as e:
					_LOGGER.warning(f"Failed to parse calendar entry: {e}")
					_LOGGER.debug(f"Entry data: {entry}")
					continue
			
			_LOGGER.info(f"Successfully parsed {len(timetable_entries)} calendar entries as timetable")
			
		except Exception as e:
			_LOGGER.error(f"Failed to parse calendar entries: {e}")
			
		return timetable_entries

	def _parse_time_registration_calendar_from_api(self, data: Dict[str, Any], pupil_id: Optional[str], start_date: datetime, end_date: datetime) -> List[TimeRegistrationEntry]:
		"""Parse time registration data from calendar entries API response.
		
		Args:
			data: Raw API response data
			pupil_id: Associated pupil ID
			start_date: Start date for parsing
			end_date: End date for parsing
			
		Returns:
			List of TimeRegistrationEntry objects
		"""
		time_registrations = []
		
		try:
			_LOGGER.debug(f"Parsing time registration calendar data with keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
			
			# Look for calendar data in various possible keys
			calendar_data = []
			for key in ['calendar', 'calendarData', 'entries', 'items', 'data', 'schedules']:
				if key in data and isinstance(data[key], list):
					calendar_data = data[key]
					_LOGGER.debug(f"Found {len(calendar_data)} calendar items in '{key}'")
					break
			
			if not calendar_data:
				_LOGGER.warning("No time registration calendar data found in API response")
				return time_registrations
			
			for item in calendar_data:
				try:
					# Extract common fields
					item_id = str(item.get('id', ''))
					date = self._parse_date(item.get('date', item.get('scheduleDate', item.get('registrationDate'))))
					start_time = self._parse_time(item.get('startTime', item.get('checkIn', item.get('arrivalTime'))))
					end_time = self._parse_time(item.get('endTime', item.get('checkOut', item.get('departureTime'))))
					
					# Extract additional fields
					status = item.get('status', item.get('registrationStatus', 'scheduled'))
					comment = item.get('comment', item.get('note', item.get('remarks', '')))
					is_locked = item.get('isLocked', item.get('locked', item.get('readOnly', False)))
					
					# Create time registration entry
					time_reg_entry = TimeRegistrationEntry(
						id=item_id,
						date=date or datetime.now(),
						start_time=start_time,
						end_time=end_time,
						status=status,
						comment=comment,
						is_locked=is_locked,
						pupil_id=pupil_id
					)
					
					time_registrations.append(time_reg_entry)
					_LOGGER.debug(f"Parsed time registration calendar item: {date} {start_time}-{end_time}")
					
				except Exception as e:
					_LOGGER.warning(f"Failed to parse time registration calendar item: {e}")
					continue
			
			_LOGGER.info(f"Successfully parsed {len(time_registrations)} time registration calendar entries")
			
		except Exception as e:
			_LOGGER.error(f"Failed to parse time registration calendar data: {e}")
			
		return time_registrations
		
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

	def _parse_time(self, time_str: Optional[str]) -> Optional[time]:
		"""Parse time string into time object.
		
		Args:
			time_str: Time string from API
			
		Returns:
			time object or None if parsing fails
		"""
		if not time_str:
			return None
			
		# Try various time formats that InfoMentor might use
		time_formats = [
			"%H:%M:%S",
			"%H:%M",
			"%H.%M",
		]
		
		for fmt in time_formats:
			try:
				parsed_time = datetime.strptime(time_str, fmt)
				return parsed_time.time()
			except ValueError:
				continue
				
		# If all formats fail, return None and log warning
		_LOGGER.warning(f"Failed to parse time: {time_str}")
		return None

	async def _get_timetable_post_fallback(self, pupil_id: Optional[str], start_date: datetime, end_date: datetime) -> List[TimetableEntry]:
		"""Fallback method to try POST for timetable entries if GET fails."""
		try:
			timetable_url = f"{HUB_BASE_URL}/timetable/timetable/gettimetablelist"
			headers = DEFAULT_HEADERS.copy()
			headers.update({
				"Accept": "application/json, text/javascript, */*; q=0.01",
				"X-Requested-With": "XMLHttpRequest",
				"Content-Type": "application/json; charset=UTF-8",
			})
			
			payload = {
				"startDate": start_date.strftime('%Y-%m-%d'),
				"endDate": end_date.strftime('%Y-%m-%d'),
			}
			
			_LOGGER.debug(f"Making fallback timetable POST request")
			_LOGGER.debug(f"Request payload: {payload}")
			
			async with self._session.post(timetable_url, headers=headers, json=payload) as resp:
				if resp.status == 200:
					data = await resp.json()
					_LOGGER.info("POST fallback succeeded for timetable entries")
					return self._parse_timetable_from_api(data, pupil_id, start_date, end_date)
				else:
					response_headers = dict(resp.headers)
					try:
						response_text = await resp.text()
					except:
						response_text = "Could not read response body"
					
					_LOGGER.warning(f"Timetable POST fallback also failed: HTTP {resp.status}")
					_LOGGER.warning(f"Response headers: {response_headers}")
					_LOGGER.warning(f"Response body: {response_text}")
					
		except Exception as e:
			_LOGGER.warning(f"Timetable POST fallback exception: {e}")
		
		return [] 