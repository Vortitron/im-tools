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
		"""Get timetable entries for a pupil.
		
		Args:
			pupil_id: Optional pupil ID. If provided, switches to that pupil first.
			start_date: Start date for timetable (default: today)
			end_date: End date for timetable (default: one week from start_date)
			
		Returns:
			List of timetable entries
		"""
		self._ensure_authenticated()
		
		if pupil_id:
			await self.switch_pupil(pupil_id)
			
		# Set default dates if not provided
		if not start_date:
			start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
		if not end_date:
			end_date = start_date + timedelta(weeks=1)
		
		# Try to get timetable data from the timetable app API
		try:
			# First get timetable app configuration
			app_data_url = f"{HUB_BASE_URL}/timetable/timetable/appData"
			headers = DEFAULT_HEADERS.copy()
			headers.update({
				"Accept": "application/json, text/javascript, */*; q=0.01",
				"X-Requested-With": "XMLHttpRequest",
				"Content-Type": "application/json; charset=UTF-8",
			})
			
			async with self._session.post(app_data_url, headers=headers, json={}) as resp:
				if resp.status == 200:
					app_data = await resp.json()
					_LOGGER.debug(f"Got timetable app data: {list(app_data.keys()) if isinstance(app_data, dict) else 'Not a dict'}")
					
					# Look for timetable data endpoints in the app data
					if 'urls' in app_data:
						urls = app_data['urls']
						_LOGGER.debug(f"Timetable URLs available: {list(urls.keys())}")
						
						# Try to get actual timetable data
						for url_key in ['getEntries', 'getData', 'getTimetable']:
							if url_key in urls:
								data_url = f"{HUB_BASE_URL}{urls[url_key]}"
								payload = {
									"startDate": start_date.strftime('%Y-%m-%d'),
									"endDate": end_date.strftime('%Y-%m-%d'),
								}
								
								async with self._session.post(data_url, headers=headers, json=payload) as data_resp:
									if data_resp.status == 200:
										data = await data_resp.json()
										return self._parse_timetable_from_api(data, pupil_id, start_date, end_date)
				else:
					_LOGGER.warning(f"Failed to get timetable app data: HTTP {resp.status}")
					
		except Exception as e:
			_LOGGER.warning(f"Failed to get timetable via API: {e}")
		
		# Fallback to calendar API which might contain timetable data
		try:
			calendar_entries_url = f"{HUB_BASE_URL}/calendarv2/calendarv2/getentries"
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
			
			async with self._session.post(calendar_entries_url, headers=headers, json=payload) as resp:
				if resp.status == 200:
					data = await resp.json()
					return self._parse_calendar_entries_as_timetable(data, pupil_id, start_date, end_date)
				else:
					_LOGGER.warning(f"Failed to get calendar entries: HTTP {resp.status}")
					
		except Exception as e:
			_LOGGER.warning(f"Failed to get calendar entries: {e}")
		
		# If all API methods fail, return empty list
		_LOGGER.warning("All timetable data retrieval methods failed")
		return []
			
	async def get_time_registration(self, pupil_id: Optional[str] = None, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> List[TimeRegistrationEntry]:
		"""Get time registration entries for a pupil (preschool/fritids).
		
		Args:
			pupil_id: Optional pupil ID. If provided, switches to that pupil first.
			start_date: Start date for registration (default: today)
			end_date: End date for registration (default: one week from start_date)
			
		Returns:
			List of time registration entries
		"""
		self._ensure_authenticated()
		
		if pupil_id:
			await self.switch_pupil(pupil_id)
			
		# Set default dates if not provided
		if not start_date:
			start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
		if not end_date:
			end_date = start_date + timedelta(weeks=1)
		
		# Use the discovered time registration API
		try:
			time_reg_url = f"{HUB_BASE_URL}/TimeRegistration/TimeRegistration/GetTimeRegistrations/"
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
			
			async with self._session.post(time_reg_url, headers=headers, json=payload) as resp:
				if resp.status == 200:
					data = await resp.json()
					return self._parse_time_registration_from_api(data, pupil_id, start_date, end_date)
				else:
					_LOGGER.warning(f"Failed to get time registrations: HTTP {resp.status}")
					
		except Exception as e:
			_LOGGER.warning(f"Failed to get time registrations: {e}")
		
		# Try alternative time registration calendar data endpoint
		try:
			time_cal_url = f"{HUB_BASE_URL}/TimeRegistration/TimeRegistration/GetCalendarData/"
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
			
			async with self._session.post(time_cal_url, headers=headers, json=payload) as resp:
				if resp.status == 200:
					data = await resp.json()
					return self._parse_time_registration_calendar_from_api(data, pupil_id, start_date, end_date)
				else:
					_LOGGER.warning(f"Failed to get time registration calendar data: HTTP {resp.status}")
					
		except Exception as e:
			_LOGGER.warning(f"Failed to get time registration calendar data: {e}")
		
		# If all methods fail, return empty list
		_LOGGER.warning("All time registration data retrieval methods failed")
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
		timetable_entries = await self.get_timetable(pupil_id, start_date, end_date)
		time_registrations = await self.get_time_registration(pupil_id, start_date, end_date)
		
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
		
		# Try different patterns to extract pupil names
		patterns = [
			# Pattern 1: Pupil switcher links
			rf'/Account/PupilSwitcher/SwitchPupil/{re.escape(pupil_id)}[^>]*>([^<]+)<',
			# Pattern 2: Data attributes
			rf'data-pupil-id="{re.escape(pupil_id)}"[^>]*>([^<]+)<',
			# Pattern 3: JavaScript pupil data
			rf'"pupilId"\s*:\s*"{re.escape(pupil_id)}"[^}}]*"name"\s*:\s*"([^"]+)"',
			rf'"id"\s*:\s*"{re.escape(pupil_id)}"[^}}]*"name"\s*:\s*"([^"]+)"',
			# Pattern 4: Select options
			rf'<option[^>]*value="{re.escape(pupil_id)}"[^>]*>([^<]+)</option>',
		]
		
		for pattern in patterns:
			matches = re.findall(pattern, html_content, re.IGNORECASE | re.DOTALL)
			for match in matches:
				name = match.strip() if isinstance(match, str) else match[0].strip()
				if name and len(name) > 1 and not name.isdigit():
					_LOGGER.debug(f"Extracted name '{name}' for pupil {pupil_id}")
					return name
		
		_LOGGER.debug(f"No name found for pupil {pupil_id}")
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
					elif is_locked:
						status = "locked"
					elif not start_time or not end_time:
						status = "not_scheduled"
					
					# Create time registration entry
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
					_LOGGER.debug(f"Parsed time registration: {reg_date.strftime('%Y-%m-%d')} {start_time}-{end_time} [{status}]")
					
				except Exception as e:
					_LOGGER.warning(f"Failed to parse time registration day: {e}")
					_LOGGER.debug(f"Day data: {day}")
					continue
			
			_LOGGER.info(f"Successfully parsed {len(time_registrations)} time registration entries")
			
		except Exception as e:
			_LOGGER.error(f"Failed to parse time registration data: {e}")
			
		return time_registrations

	def _parse_calendar_entries_as_timetable(self, data: Dict[str, Any], pupil_id: Optional[str], start_date: datetime, end_date: datetime) -> List[TimetableEntry]:
		"""Parse timetable data from calendar entries API response.
		
		Args:
			data: Raw API response data (list of calendar entries)
			pupil_id: Associated pupil ID
			start_date: Start date for parsing
			end_date: End date for parsing
			
		Returns:
			List of TimetableEntry objects
		"""
		timetable_entries = []
		
		try:
			# The calendar API returns a list directly
			if isinstance(data, list):
				entries = data
			elif isinstance(data, dict) and 'entries' in data:
				entries = data['entries']
			else:
				_LOGGER.warning("No calendar entries found in API response")
				return timetable_entries
			
			_LOGGER.debug(f"Found {len(entries)} calendar entries to parse")
			
			for entry in entries:
				try:
					# Extract fields from actual InfoMentor structure
					entry_id = str(entry.get('id', ''))
					title = entry.get('title', '')
					description = entry.get('text', entry.get('description', ''))
					
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
					calendar_entry_type_id = entry.get('calendarEntryTypeId')
					subjects = entry.get('subjects', [])
					courses = entry.get('courses', [])
					
					# Determine subject from available data
					subject = ""
					if subjects:
						subject = subjects[0] if isinstance(subjects, list) else str(subjects)
					elif courses:
						subject = courses[0] if isinstance(courses, list) else str(courses)
					
					# Create timetable entry
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
					_LOGGER.debug(f"Parsed calendar entry: {title} on {entry_date.strftime('%Y-%m-%d')}")
					
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