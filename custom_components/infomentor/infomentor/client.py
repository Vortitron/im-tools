"""Main client for InfoMentor API."""

import json
import logging
from datetime import datetime, time, timedelta
from typing import List, Optional, Dict, Any

import aiohttp
import asyncio

from .auth import InfoMentorAuth, HUB_BASE_URL, MODERN_BASE_URL, DEFAULT_HEADERS
from .models import (
	NewsItem, TimelineEntry, PupilInfo, Assignment, AttendanceEntry,
	TimetableEntry, TimeRegistrationEntry, ScheduleDay,
	InfoMentorNotification,
)
from .exceptions import InfoMentorAPIError, InfoMentorConnectionError, InfoMentorDataError, InfoMentorAuthError

_LOGGER = logging.getLogger(__name__)


class InfoMentorClient:
	"""Client for interacting with InfoMentor API."""
	
	def __init__(self, session: Optional[aiohttp.ClientSession] = None, storage=None):
		"""Initialise InfoMentor client.
		
		Args:
			session: Optional aiohttp session. If None, a new one will be created.
			storage: Optional storage for persisting school selection
		"""
		self._session = session
		self._own_session = session is None
		self.storage = storage
		self.auth: Optional[InfoMentorAuth] = None
		self.authenticated = False
		
	async def __aenter__(self):
		"""Async context manager entry."""
		if self._own_session:
			self._session = aiohttp.ClientSession()
		self.auth = InfoMentorAuth(self._session, self.storage)
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
		if self.authenticated:
			try:
				await self.warmup_hub_session()
			except Exception as err:
				_LOGGER.debug("Post-login hub warmup failed: %s", err)
		return self.authenticated

	async def try_restore_session(self) -> bool:
		"""Attempt to reuse stored cookies instead of running a full login."""
		if not self.auth:
			raise InfoMentorAPIError("Client not properly initialised")

		self.authenticated = await self.auth.try_restore_session()
		if self.authenticated:
			try:
				await self.warmup_hub_session()
			except Exception as err:
				_LOGGER.debug("Post-restore hub warmup failed: %s", err)
		return self.authenticated
		
	async def get_pupil_ids(self) -> List[str]:
		"""Get list of pupil IDs available for this account.
		
		Returns:
			List of pupil ID strings
		"""
		self._ensure_authenticated()
		return self.auth.pupil_ids.copy()
		
	async def switch_pupil(self, pupil_id: str) -> bool:
		"""Switch to a specific pupil context.
		
		Args:
			pupil_id: ID of pupil to switch to
			
		Returns:
			True if switch successful, False otherwise
		"""
		# Validate inputs first
		if not pupil_id or pupil_id == "None" or pupil_id.lower() == "none":
			_LOGGER.error(f"Invalid pupil ID for switch_pupil: {pupil_id!r}")
			return False
			
		if not hasattr(self, 'auth') or not self.auth:
			_LOGGER.error("No auth object available for pupil switching")
			return False
			
		if not self.auth.pupil_ids:
			_LOGGER.error("No pupil IDs available for switching")
			return False
		
		if pupil_id not in self.auth.pupil_ids:
			_LOGGER.error(f"Pupil ID {pupil_id} not found in available pupils: {self.auth.pupil_ids}")
			return False
		
		try:
			result = await self.auth.switch_pupil(pupil_id)
			if result:
				_LOGGER.debug(f"Successfully switched to pupil {pupil_id}")
			else:
				_LOGGER.warning(f"Failed to switch to pupil {pupil_id}")
			return result
		except Exception as e:
			_LOGGER.error(f"Exception during pupil switch to {pupil_id}: {e}")
			return False
		
	async def get_news(self, pupil_id: Optional[str] = None) -> List[NewsItem]:
		"""Get news items for a pupil.
		
		Args:
			pupil_id: Optional pupil ID. If provided, switches to that pupil first.
			
		Returns:
			List of news items
		"""
		self._ensure_authenticated()
		
		if pupil_id and not await self.switch_pupil(pupil_id):
			# Otherwise we'd return the previously selected pupil's news under this ID
			raise InfoMentorAPIError(f"Could not switch to pupil {pupil_id} for news")
			
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
				
				# Check content type before attempting JSON decode
				content_type = resp.headers.get('content-type', '').lower()
				if 'text/html' in content_type:
					# If we get HTML instead of JSON, session likely expired
					_LOGGER.warning(f"Got HTML response instead of JSON for news - session may have expired")
					raise InfoMentorAuthError("Session expired - received HTML instead of JSON")
				
				try:
					data = await resp.json()
				except aiohttp.ContentTypeError as e:
					# Handle cases where content-type header is wrong but content might still be JSON
					text = await resp.text()
					_LOGGER.warning(f"Content-type error for news, attempting manual JSON parse: {e}")
					if text.strip().startswith('{') or text.strip().startswith('['):
						try:
							data = json.loads(text)
						except json.JSONDecodeError:
							_LOGGER.error(f"Failed to parse response as JSON: {text[:200]}...")
							raise InfoMentorDataError("Invalid JSON response from news endpoint")
					else:
						_LOGGER.error(f"Response doesn't look like JSON: {text[:200]}...")
						raise InfoMentorAuthError("Authentication may have failed - non-JSON response")
				
				return self._parse_news_data(data, pupil_id)
				
		except aiohttp.ClientError as e:
			raise InfoMentorConnectionError(f"Connection error: {e}") from e
		except json.JSONDecodeError as e:
			raise InfoMentorDataError(f"Failed to parse news data: {e}") from e
			
	async def warmup_hub_session(self) -> bool:
		"""Replay the browser SPA warm-up calls so the hub server session is primed.

		The hub APIs (timeline, notifications, etc.) return empty 200s, 500s or
		HTML if we call them before the SPA has initialised "home". The real
		browser sends a small sequence of GETs to bootstrap the server session
		after login — we replicate the important ones here so subsequent API
		calls don't get half-baked responses.

		Returns True if the warm-up completed without errors.
		"""
		if not self._session or not self.authenticated:
			return False

		# (method, path) — InfoMentor's *App/*App/appData endpoints expect POST.
		warmup_steps = [
			("GET", "/"),
			("GET", "/Account/ClearToHome"),
			("POST", "/Home/Home/appData"),
			("POST", "/NotificationApp/NotificationApp/appData"),
			("GET", "/Authentication/Authentication/AccessibilityInfo"),
		]

		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Accept": "application/json, text/javascript, */*; q=0.01",
			"X-Requested-With": "XMLHttpRequest",
			"Referer": f"{HUB_BASE_URL}/",
			"Origin": HUB_BASE_URL,
		})

		any_success = False
		for method, path in warmup_steps:
			url = f"{HUB_BASE_URL}{path}"
			req = self._session.get if method == "GET" else self._session.post
			try:
				async with req(url, headers=headers, allow_redirects=True) as resp:
					body = await resp.text()
					_LOGGER.debug(
						"Hub warmup %s %s -> %s (%d chars, ct=%s)",
						method, path, resp.status, len(body),
						resp.headers.get("content-type", ""),
					)
					if resp.status < 500:
						any_success = True
			except Exception as err:
				_LOGGER.debug("Hub warmup %s %s failed: %s", method, path, err)

		return any_success

	async def get_notifications(self) -> List[InfoMentorNotification]:
		"""Fetch notifications from the InfoMentor NotificationApp.

		Returns all notifications for the current session (all pupils).

		InfoMentor's hub returns:
		  - HTTP 500 when the session is completely invalid
		  - HTTP 200 with HTML when the cookie is present but expired
		  - HTTP 200 with an empty body when the server-side SPA session hasn't
		    been primed yet (no prior "home init" call)
		  - HTTP 200 with JSON when everything is healthy

		If we get an empty/HTML/500 response we run the hub warm-up and retry once.
		"""
		self._ensure_authenticated()

		url = f"{HUB_BASE_URL}/NotificationApp/NotificationApp/appData"
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Accept": "application/json, text/javascript, */*; q=0.01",
			"X-Requested-With": "XMLHttpRequest",
			"Referer": f"{HUB_BASE_URL}/",
			"Origin": HUB_BASE_URL,
		})

		async def _debug_dump(tag: str, status: int, content_type: str, text: str) -> None:
			if not _LOGGER.isEnabledFor(logging.DEBUG):
				return
			try:
				import asyncio as _asyncio
				path = f"/tmp/infomentor_notifications_{tag}.txt"
				def _w():
					with open(path, "w", encoding="utf-8") as f:
						f.write(f"status={status}\ncontent-type={content_type}\n\n{text}")
				await _asyncio.to_thread(_w)
				_LOGGER.debug("Dumped notification response to %s", path)
			except Exception as e:
				_LOGGER.debug("Could not dump notification response: %s", e)

		async def _do_request(method: str) -> Optional[List[InfoMentorNotification]]:
			"""Return list on success, None if we should retry after warmup."""
			request_fn = self._session.get if method == "GET" else self._session.post
			try:
				async with request_fn(url, headers=headers) as resp:
					status = resp.status
					content_type = resp.headers.get("content-type", "").lower()
					text = await resp.text()

					if status != 200:
						_LOGGER.warning("Notification endpoint %s returned HTTP %s", method, status)
						await _debug_dump(f"{method.lower()}_{status}", status, content_type, text)
						return None

					if "text/html" in content_type:
						_LOGGER.warning("Notification endpoint %s returned HTML — session may have expired", method)
						await _debug_dump(f"{method.lower()}_html", status, content_type, text)
						return None

					stripped = text.strip()
					if not stripped:
						_LOGGER.warning("Notification endpoint %s returned empty body (content-type=%s)", method, content_type)
						await _debug_dump(f"{method.lower()}_empty", status, content_type, text)
						return None

					if not (stripped.startswith("{") or stripped.startswith("[")):
						_LOGGER.warning("Notification endpoint %s returned non-JSON (%d chars)", method, len(text))
						await _debug_dump(f"{method.lower()}_nonjson", status, content_type, text)
						return None

					try:
						data = json.loads(stripped)
					except json.JSONDecodeError as e:
						_LOGGER.warning("Notification JSON parse failed (%s)", e)
						await _debug_dump(f"{method.lower()}_jsonerr", status, content_type, text)
						return None

					raw_items = data.get("notifications", []) if isinstance(data, dict) else []
					notifications: List[InfoMentorNotification] = []
					for item in raw_items:
						try:
							notifications.append(InfoMentorNotification.from_dict(item))
						except Exception as parse_err:
							_LOGGER.debug("Failed to parse notification: %s", parse_err)

					_LOGGER.debug("Fetched %d notifications via %s", len(notifications), method)
					return notifications
			except aiohttp.ClientError as e:
				raise InfoMentorConnectionError(f"Connection error fetching notifications: {e}") from e

		# InfoMentor's /NotificationApp/NotificationApp/appData endpoint currently
		# requires POST; GET returns HTTP 500. We try POST first and fall back to
		# GET + warm-up if the account happens to be one of the older variants.
		result = await _do_request("POST")
		if result is not None:
			return result

		_LOGGER.info("Notification POST failed; running hub warmup and trying GET fallback")
		await self.warmup_hub_session()

		result = await _do_request("POST")
		if result is not None:
			return result

		result = await _do_request("GET")
		if result is not None:
			return result

		_LOGGER.warning("Notification endpoint returned no usable data after warmup + POST/GET attempts")
		# Raise rather than return [] so callers keep the last good list
		raise InfoMentorAPIError("Notification endpoint returned no usable data")

	async def _hub_post_json(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
		"""POST to a hub app endpoint and return the decoded JSON body."""
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Accept": "application/json, text/javascript, */*; q=0.01",
			"X-Requested-With": "XMLHttpRequest",
			"Referer": f"{HUB_BASE_URL}/",
			"Origin": HUB_BASE_URL,
		})
		kwargs: Dict[str, Any] = {"json": payload} if payload is not None else {"data": b""}
		try:
			async with self._session.post(f"{HUB_BASE_URL}{path}", headers=headers, **kwargs) as resp:
				text = await resp.text()
				if resp.status != 200:
					raise InfoMentorAPIError(f"{path}: HTTP {resp.status}")
		except aiohttp.ClientError as e:
			raise InfoMentorConnectionError(f"Connection error: {e}") from e
		try:
			return json.loads(text)
		except json.JSONDecodeError as e:
			raise InfoMentorDataError(f"{path}: non-JSON response") from e

	async def _switch_for_app(self, pupil_id: Optional[str]) -> None:
		if pupil_id and not await self.switch_pupil(pupil_id):
			raise InfoMentorAPIError(f"Could not switch to pupil {pupil_id}")

	async def get_calendar_entries(self, pupil_id: Optional[str], start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
		"""Raw calendar events (title, text, startDate, startTime, isAllDayEvent, ...) for a pupil."""
		self._ensure_authenticated()
		await self._switch_for_app(pupil_id)
		# The app endpoints only answer after the app has been initialised
		await self._hub_post_json("/calendarv2/calendarv2/appData")
		data = await self._hub_post_json("/calendarv2/calendarv2/getentries", {
			"startDate": start_date.strftime('%Y-%m-%d'),
			"endDate": end_date.strftime('%Y-%m-%d'),
		})
		return data if isinstance(data, list) else []

	async def get_learnlogs(self, pupil_id: Optional[str]) -> List[Dict[str, Any]]:
		"""Raw learning-log posts (newest first) for a pupil."""
		self._ensure_authenticated()
		await self._switch_for_app(pupil_id)
		await self._hub_post_json("/learnlog/learnlog/appData")
		data = await self._hub_post_json("/learnlog/learnlog/getlearnlogs", {})
		return data if isinstance(data, list) else []

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
		
		if pupil_id and not await self.switch_pupil(pupil_id):
			# Otherwise we'd return the previously selected pupil's timeline under this ID
			raise InfoMentorAPIError(f"Could not switch to pupil {pupil_id} for timeline")
			
		# First, initialise timeline app data
		app_data_url = f"{HUB_BASE_URL}/grouptimeline/grouptimeline/appData"
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Accept": "application/json, text/javascript, */*; q=0.01",
			"X-Requested-With": "XMLHttpRequest",
			"Content-Length": "0",
			"Referer": f"{HUB_BASE_URL}/",
			"Origin": HUB_BASE_URL,
		})

		async def _init_timeline() -> int:
			async with self._session.post(app_data_url, headers=headers) as resp:
				return resp.status

		init_status = await _init_timeline()
		if init_status != 200:
			_LOGGER.warning("Failed to initialise timeline app data: HTTP %s; running hub warmup and retrying", init_status)
			await self.warmup_hub_session()
			if pupil_id:
				try:
					await self.switch_pupil(pupil_id)
				except Exception as err:
					_LOGGER.debug("Pupil switch during timeline retry failed: %s", err)
			init_status = await _init_timeline()
			if init_status != 200:
				_LOGGER.warning("Timeline init still returned HTTP %s after warmup", init_status)
		
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
				
				# Check content type before attempting JSON decode
				content_type = resp.headers.get('content-type', '').lower()
				if 'text/html' in content_type:
					_LOGGER.warning(f"Got HTML response instead of JSON for timeline - session may have expired")
					raise InfoMentorAuthError("Session expired - received HTML instead of JSON")
				
				try:
					data = await resp.json()
				except aiohttp.ContentTypeError as e:
					text = await resp.text()
					_LOGGER.warning(f"Content-type error for timeline, attempting manual JSON parse: {e}")
					if text.strip().startswith('{') or text.strip().startswith('['):
						try:
							data = json.loads(text)
						except json.JSONDecodeError:
							_LOGGER.error(f"Failed to parse timeline response as JSON: {text[:200]}...")
							raise InfoMentorDataError("Invalid JSON response from timeline endpoint")
					else:
						_LOGGER.error(f"Timeline response doesn't look like JSON: {text[:200]}...")
						raise InfoMentorAuthError("Authentication may have failed - non-JSON response")
				
				return self._parse_timeline_data(data, pupil_id)
				
		except aiohttp.ClientError as e:
			raise InfoMentorConnectionError(f"Connection error: {e}") from e
		except json.JSONDecodeError as e:
			raise InfoMentorDataError(f"Failed to parse timeline data: {e}") from e

	async def get_timetable(self, pupil_id: Optional[str] = None, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> List[TimetableEntry]:
		"""Get timetable entries for a pupil (school lessons).
		
		Args:
			pupil_id: Optional pupil ID. If provided, switches to that pupil first.
			start_date: Start date for timetable (default: today)
			end_date: End date for timetable (default: one week from start_date)
			
		Returns:
			List of TimetableEntry objects
		"""
		self._ensure_authenticated()
		
		# Check if we have any pupils available at all
		if not self.auth or not self.auth.pupil_ids:
			_LOGGER.warning("No pupils available for timetable retrieval")
			return []
		
		if pupil_id:
			# Validate that the pupil_id exists
			if pupil_id not in self.auth.pupil_ids:
				_LOGGER.warning(f"Pupil {pupil_id} not found in available pupils for timetable: {self.auth.pupil_ids}")
				return []
			
			# Try switching up to 2 times if it fails
			switch_success = False
			for attempt in range(2):
				switch_result = await self.switch_pupil(pupil_id)
				if switch_result:
					switch_success = True
					_LOGGER.debug(f"Successfully switched to pupil {pupil_id} for timetable (attempt {attempt + 1})")
					# Add extra delay after switch to ensure session propagation
					await asyncio.sleep(3.0)
					break
				else:
					_LOGGER.warning(f"Switch attempt {attempt + 1} failed for pupil {pupil_id}")
					if attempt == 0:  # Retry once with a delay
						await asyncio.sleep(2.0)
			
			if not switch_success:
				_LOGGER.warning(f"Failed to switch to pupil {pupil_id} for timetable after 2 attempts")
				return []
		else:
			# If no pupil_id provided, check if we have a current pupil context
			# This handles cases where get_schedule already switched to a pupil
			if not hasattr(self.auth, 'current_pupil_id') or not self.auth.current_pupil_id:
				_LOGGER.debug("No pupil_id provided and no current pupil context - using first available pupil")
				if self.auth.pupil_ids:
					first_pupil = self.auth.pupil_ids[0]
					switch_result = await self.switch_pupil(first_pupil)
					if not switch_result:
						_LOGGER.warning(f"Failed to switch to first available pupil {first_pupil} for timetable")
						return []
				else:
					_LOGGER.warning("No pupils available for timetable retrieval")
					return []

		# Set default dates if not provided
		if not start_date:
			start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
		if not end_date:
			end_date = start_date + timedelta(weeks=1)
		
		_LOGGER.debug(f"Getting timetable data for pupil {pupil_id} from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
		
		# Use simple GET request to timetable API
		try:
			return await self._get_timetable_get_primary(pupil_id, start_date, end_date)
		except Exception as e:
			_LOGGER.warning(f"Timetable retrieval failed for pupil {pupil_id}: {e}")
			return []
	
	async def _get_timetable_get_primary(self, pupil_id: Optional[str], start_date: datetime, end_date: datetime) -> List[TimetableEntry]:
		"""Primary GET method for timetable retrieval."""
		timetable_url = f"{HUB_BASE_URL}/timetable/timetable/gettimetablelist"
		headers = DEFAULT_HEADERS.copy()
		headers.update({
			"Accept": "application/json, text/javascript, */*; q=0.01",
			"X-Requested-With": "XMLHttpRequest",
		})
		
		params = {
			# The hub honours start/end (end exclusive) and ignores startDate/endDate,
			# which on their own return a fixed 7-day window from today
			"start": start_date.strftime('%Y-%m-%d'),
			"end": (end_date + timedelta(days=1)).strftime('%Y-%m-%d'),
			"startDate": start_date.strftime('%Y-%m-%d'),
			"endDate": end_date.strftime('%Y-%m-%d'),
		}
		
		_LOGGER.debug(f"Making timetable GET request to {timetable_url}")
		_LOGGER.debug(f"Request params: {params}")
		
		async with self._session.get(timetable_url, headers=headers, params=params) as resp:
			if resp.status == 200:
				# Check content type before attempting JSON decode
				content_type = resp.headers.get('content-type', '').lower()
				if 'text/html' in content_type:
					_LOGGER.warning(f"Got HTML response instead of JSON for timetable - session may have expired")
					raise InfoMentorAuthError("Session expired - received HTML instead of JSON")
				
				try:
					data = await resp.json()
				except aiohttp.ContentTypeError as e:
					text = await resp.text()
					_LOGGER.warning(f"Content-type error for timetable, attempting manual JSON parse: {e}")
					if text.strip().startswith('{') or text.strip().startswith('['):
						try:
							data = json.loads(text)
						except json.JSONDecodeError:
							_LOGGER.error(f"Failed to parse timetable response as JSON: {text[:200]}...")
							raise InfoMentorDataError("Invalid JSON response from timetable endpoint")
					else:
						_LOGGER.error(f"Timetable response doesn't look like JSON: {text[:200]}...")
						raise InfoMentorAuthError("Authentication may have failed - non-JSON response")
				
				if isinstance(data, list):
					_LOGGER.debug(f"Got timetable data: List with {len(data)} items")
					if not data:
						_LOGGER.warning(f"Timetable API returned empty list for pupil {pupil_id} ({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')})")
				elif isinstance(data, dict):
					_LOGGER.debug(f"Got timetable data: Dict with keys {list(data.keys())}")
				else:
					_LOGGER.debug(f"Got timetable data: {type(data)}")
				
				return self._parse_timetable_from_api(data, pupil_id, start_date, end_date)
			elif resp.status in [401, 403]:
				_LOGGER.warning(f"Authentication error for timetable (HTTP {resp.status}) - session may have expired")
				raise InfoMentorAuthError("Session expired during timetable access")
			elif resp.status == 500:
				response_text = await resp.text()
				if "HandleUnauthorizedRequest" in response_text:
					_LOGGER.warning(f"Session context issue for pupil {pupil_id} - unauthorized for timetable")
					raise InfoMentorAuthError("Pupil context unauthorized for timetable access")
				else:
					_LOGGER.warning(f"Server error retrieving timetable: {response_text}")
					raise InfoMentorAPIError(f"Server error: HTTP {resp.status}")
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
				
				# If GET fails with "Invalid Verb" or similar, raise specific error
				if "invalid verb" in response_text.lower() or "bad request" in response_text.lower():
					raise InfoMentorAPIError("GET method not supported for timetable endpoint")
				
				raise InfoMentorAPIError(f"Timetable API error: HTTP {resp.status}")
	


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
			
			# The API ignores startDate/endDate and returns the Mon-Fri week containing
			# `date`, so request every week in the range and combine the days.
			week_days: List[Dict[str, Any]] = []
			week = start_date - timedelta(days=start_date.weekday())
			while week <= end_date:
				params = {
					"date": week.strftime('%Y-%m-%d'),
					"startDate": start_date.strftime('%Y-%m-%d'),
					"endDate": end_date.strftime('%Y-%m-%d'),
				}
				_LOGGER.debug(f"Time registration GET {time_reg_url} params={params}")
				
				async with self._session.get(time_reg_url, headers=headers, params=params) as resp:
					if resp.status == 200:
						# Check content type before attempting JSON decode
						content_type = resp.headers.get('content-type', '').lower()
						if 'text/html' in content_type:
							_LOGGER.warning(f"Got HTML response instead of JSON for time registration - session may have expired")
							raise InfoMentorAuthError("Session expired - received HTML instead of JSON")
					
						try:
							data = await resp.json()
						except aiohttp.ContentTypeError as e:
							text = await resp.text()
							_LOGGER.warning(f"Content-type error for time registration, attempting manual JSON parse: {e}")
							if text.strip().startswith('{') or text.strip().startswith('['):
								try:
									data = json.loads(text)
								except json.JSONDecodeError:
									_LOGGER.error(f"Failed to parse time registration response as JSON: {text[:200]}...")
									raise InfoMentorDataError("Invalid JSON response from time registration endpoint")
							else:
								_LOGGER.error(f"Time registration response doesn't look like JSON: {text[:200]}...")
								raise InfoMentorAuthError("Authentication may have failed - non-JSON response")
					
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
					
						week_days.extend(data.get('days', []))
					elif resp.status in [401, 403]:
						_LOGGER.warning(f"Authentication error for time registration (HTTP {resp.status}) - session may have expired")
						return []
					else:
						response_headers = dict(resp.headers)
						try:
							response_text = await resp.text()
						except:
							response_text = "Could not read response body"
					
						_LOGGER.warning(f"Failed to get time registrations: HTTP {resp.status}")
						_LOGGER.warning(f"Time registrations response headers: {response_headers}")
						_LOGGER.warning(f"Time registrations response body: {response_text}")
					
						# If GET fails with "Invalid Verb", try POST fallback
						if "invalid verb" in response_text.lower() or "bad request" in response_text.lower():
							_LOGGER.info("Time registration GET failed with verb error, trying POST fallback...")
							return await self._get_time_registration_post_fallback(pupil_id, start_date, end_date, time_reg_url)
						if week_days:
							break  # keep the weeks we already have
						raise InfoMentorAPIError(f"Time registrations HTTP {resp.status}")
				week += timedelta(days=7)
			
			return self._parse_time_registration_from_api({'days': week_days}, pupil_id, start_date, end_date)
					
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
					# Check content type before attempting JSON decode
					content_type = resp.headers.get('content-type', '').lower()
					if 'text/html' in content_type:
						_LOGGER.warning(f"Got HTML response instead of JSON for time registration calendar - session may have expired")
						raise InfoMentorAuthError("Session expired - received HTML instead of JSON")
					
					try:
						data = await resp.json()
					except aiohttp.ContentTypeError as e:
						text = await resp.text()
						_LOGGER.warning(f"Content-type error for time registration calendar, attempting manual JSON parse: {e}")
						if text.strip().startswith('{') or text.strip().startswith('['):
							try:
								data = json.loads(text)
							except json.JSONDecodeError:
								_LOGGER.error(f"Failed to parse time registration calendar response as JSON: {text[:200]}...")
								raise InfoMentorDataError("Invalid JSON response from time registration calendar endpoint")
						else:
							_LOGGER.error(f"Time registration calendar response doesn't look like JSON: {text[:200]}...")
							raise InfoMentorAuthError("Authentication may have failed - non-JSON response")
					
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

	async def get_schedule(self, pupil_id: str, start_date: datetime, end_date: datetime) -> List[ScheduleDay]:
		"""Get schedule for a pupil between two dates.
		
		Args:
			pupil_id: ID of pupil
			start_date: Start date for schedule
			end_date: End date for schedule
			
		Returns:
			List of schedule days
		"""
		# Validate pupil_id before making API calls
		if not pupil_id or pupil_id == "None" or pupil_id.lower() == "none":
			_LOGGER.error(f"Invalid pupil ID for get_schedule: {pupil_id!r}")
			return []
			
		if pupil_id not in self.auth.pupil_ids:
			_LOGGER.error(f"Pupil ID {pupil_id} not found in authenticated pupils: {self.auth.pupil_ids}")
			return []
		
		# Switch to pupil context - don't proceed if switching fails
		switch_success = await self.switch_pupil(pupil_id)
		if not switch_success:
			_LOGGER.error(f"Failed to switch to pupil {pupil_id} - cannot retrieve schedule")
			return []
		
		# Get timetable (lessons)
		timetable_data = await self._get_timetable(pupil_id, start_date, end_date)
		
		# Get time registrations (attendance)
		time_reg_data = await self.get_time_registration(pupil_id, start_date, end_date)
		
		# Combine data by date
		schedule_days = []
		current_date = start_date.date()
		end = end_date.date()
		
		while current_date <= end:
			# Get timetable entries for this date
			day_timetable = [entry for entry in timetable_data if entry.date.date() == current_date]
			
			# Get time registrations for this date
			day_time_regs = [entry for entry in time_reg_data if entry.date.date() == current_date]
			
			# Create schedule day
			schedule_day = ScheduleDay(
				date=datetime.combine(current_date, datetime.min.time()),
				pupil_id=pupil_id,
				timetable_entries=day_timetable,
				time_registrations=day_time_regs
			)
			
			schedule_days.append(schedule_day)
			current_date += timedelta(days=1)
		
		return schedule_days
		
	async def _get_timetable(self, pupil_id: str, start_date: datetime, end_date: datetime) -> List[TimetableEntry]:
		"""Get timetable data for a pupil."""
		# Validate pupil_id
		if not pupil_id or pupil_id == "None" or pupil_id.lower() == "none":
			_LOGGER.error(f"Invalid pupil ID for _get_timetable: {pupil_id!r}")
			return []
			
		# Format dates for API
		start_str = start_date.strftime('%Y-%m-%d')
		end_str = end_date.strftime('%Y-%m-%d')
		
		# Try modern API first
		url = f"{MODERN_BASE_URL}/api/get/timetable/student/{pupil_id}"
		params = {
			'startDate': start_str,
			'endDate': end_str
		}
		
		headers = DEFAULT_HEADERS.copy()
		headers["Referer"] = f"{MODERN_BASE_URL}/"
		
		try:
			async with self._session.get(url, headers=headers, params=params) as resp:
				if resp.status == 200:
					# Detect HTML masquerading as JSON (session redirection)
					content_type = resp.headers.get('content-type', '').lower()
					if 'text/html' in content_type:
						text = await resp.text()
						_LOGGER.warning(f"Timetable modern API returned HTML for pupil {pupil_id}; attempting hub fallback. Snippet: {text[:200]}...")
						return await self._get_timetable_hub_fallback(pupil_id, start_date, end_date)
					data = await resp.json()
					
					if not data:
						_LOGGER.debug(f"Timetable API returned empty list for pupil {pupil_id} ({start_str} to {end_str})")
						return []
					
					timetable_entries = self._parse_timetable_from_api(data, pupil_id, start_date, end_date)
					if timetable_entries:
						_LOGGER.debug(f"Retrieved {len(timetable_entries)} timetable entries for pupil {pupil_id}")
						return timetable_entries
					_LOGGER.warning(f"Timetable API data for pupil {pupil_id} could not be parsed; trying hub fallback")
				else:
					_LOGGER.warning(f"Timetable API returned status {resp.status} for pupil {pupil_id}; trying hub fallback")
		except Exception as e:
			_LOGGER.warning(f"Failed to get timetable for pupil {pupil_id}: {e}")
		
		try:
			return await self._get_timetable_hub_fallback(pupil_id, start_date, end_date)
		except Exception as e2:
			_LOGGER.warning(f"Timetable hub fallback also failed for pupil {pupil_id}: {e2}")
		
		return []

	async def _get_timetable_hub_fallback(self, pupil_id: str, start_date: datetime, end_date: datetime) -> List[TimetableEntry]:
		"""Fallback timetable retrieval via hub timetable endpoint after ensuring pupil context.
		
		Assumes session is authenticated and pupil context has been switched.
		"""
		# Ensure correct pupil context
		switch_ok = await self.switch_pupil(pupil_id)
		if not switch_ok:
			return []
		await asyncio.sleep(1.0)
		
		# Use the known working hub endpoint that returns JSON
		try:
			return await self._get_timetable_get_primary(pupil_id, start_date, end_date)
		except Exception as e:
			_LOGGER.warning(f"Hub fallback failed for pupil {pupil_id}: {e}")
			return []

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
		
		# First try to get name from stored pupil names (from authentication)
		pupil_name = self.auth.pupil_names.get(pupil_id)
		if pupil_name:
			_LOGGER.debug(f"Using stored pupil name for {pupil_id}: {pupil_name}")
			return PupilInfo(id=pupil_id, name=pupil_name)
			
		# Fallback: Try to extract pupil name from hub page
		try:
			hub_url = f"{HUB_BASE_URL}/#/"
			headers = DEFAULT_HEADERS.copy()
			headers["Referer"] = f"{HUB_BASE_URL}/authentication/authentication/login?apitype=im1&forceOAuth=true"
			
			async with self._session.get(hub_url, headers=headers) as resp:
				if resp.status == 200:
					text = await resp.text()
					name = self._extract_pupil_name_from_hub(text, pupil_id)
					if name:
						# Store the extracted name for future use
						self.auth.pupil_names[pupil_id] = name
						return PupilInfo(id=pupil_id, name=name)
		except Exception as e:
			_LOGGER.warning(f"Failed to extract pupil name for {pupil_id}: {e}")
		
		# Final fallback to basic info
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

	def _parse_timetable_from_api(self, data: Any, pupil_id: Optional[str], start_date: datetime, end_date: datetime) -> List[TimetableEntry]:
		"""Parse timetable data from API response.
		
		Args:
			data: Raw API response data (can be dict or list)
			pupil_id: Associated pupil ID
			start_date: Start date for parsing
			end_date: End date for parsing
			
		Returns:
			List of TimetableEntry objects
		"""
		timetable_entries = []
		
		try:
			_LOGGER.debug(f"Parsing timetable API data: {type(data)} - {list(data.keys()) if isinstance(data, dict) else f'List with {len(data)} items' if isinstance(data, list) else 'Other type'}")
			
			# Handle both dict and list responses
			entries = []
			
			if isinstance(data, list):
				# API returned a list directly
				entries = data
				_LOGGER.debug(f"Timetable API returned list with {len(entries)} entries")
			elif isinstance(data, dict):
				# API returned a dict, look for entries in various possible keys
				for key in ['entries', 'events', 'items', 'data', 'timetableEntries', 'lessons']:
					if key in data and isinstance(data[key], list):
						entries = data[key]
						_LOGGER.debug(f"Found {len(entries)} entries in '{key}'")
						break
			else:
				_LOGGER.warning(f"Unexpected timetable data type: {type(data)}")
				return timetable_entries
			
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
					start_date_parsed = self._parse_date_or_none(entry.get('startDate', entry.get('start', entry.get('date'))))
					if start_date_parsed is None:
						_LOGGER.warning(f"Skipping timetable entry without a parsable date: {entry_id} {title!r}")
						continue
					start_time = self._parse_time(entry.get('startTime', entry.get('start')))
					end_time = self._parse_time(entry.get('endTime', entry.get('end')))
					
					# Extract additional fields (the hub puts teacher/room under "notes")
					notes = entry.get('notes') if isinstance(entry.get('notes'), dict) else {}
					subject = entry.get('subject', entry.get('course', title))
					teacher = entry.get('teacher', entry.get('instructor', entry.get('staff'))) or notes.get('tutors') or ''
					room = entry.get('room', entry.get('location', entry.get('classroom'))) or notes.get('roomInfo') or ''
					entry_type = entry.get('type', entry.get('entryType', entry.get('lessonType', 'lesson')))
					
					# Create timetable entry
					timetable_entry = TimetableEntry(
						id=entry_id,
						title=title,
						description=description,
						date=start_date_parsed,
						start_time=start_time,
						end_time=end_time,
						subject=subject,
						teacher=teacher,
						room=room,
						entry_type=entry_type,
						is_all_day=bool(entry.get('allDay', entry.get('isAllDay', False))),
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
					reg_date = self._parse_date_or_none(date_str)
					if reg_date is None:
						_LOGGER.warning(f"Skipping time registration without a parsable date: {date_str!r}")
						continue
					
					# Parse time information
					start_datetime_str = day.get('startDateTime')
					end_datetime_str = day.get('endDateTime')
					
					start_time = None
					end_time = None
					
					if start_datetime_str:
						start_datetime = self._parse_date_or_none(start_datetime_str)
						start_time = start_datetime.time() if start_datetime else None
					
					if end_datetime_str:
						end_datetime = self._parse_date_or_none(end_datetime_str)
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
					date = self._parse_date_or_none(item.get('date', item.get('scheduleDate', item.get('registrationDate'))))
					if date is None:
						_LOGGER.warning(f"Skipping time registration calendar item without a parsable date: {item_id}")
						continue
					start_time = self._parse_time(item.get('startTime', item.get('checkIn', item.get('arrivalTime'))))
					end_time = self._parse_time(item.get('endTime', item.get('checkOut', item.get('departureTime'))))
					
					# Extract additional fields
					status = item.get('status', item.get('registrationStatus', 'scheduled'))
					comment = item.get('comment', item.get('note', item.get('remarks', '')))
					is_locked = item.get('isLocked', item.get('locked', item.get('readOnly', False)))
					
					# Create time registration entry
					time_reg_entry = TimeRegistrationEntry(
						id=item_id,
						date=date,
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
		"""Parse date string into datetime object, falling back to now.
		
		Only use this where a wrong date is harmless (e.g. news). Schedule
		parsing uses _parse_date_or_none so unparsable entries are skipped
		rather than landing on today.
		
		Args:
			date_str: Date string from API
			
		Returns:
			datetime object
		"""
		return self._parse_date_or_none(date_str) or datetime.now()

	def _parse_date_or_none(self, date_str: Optional[str]) -> Optional[datetime]:
		"""Parse date string into a naive datetime, or None if missing/unparsable."""
		if not date_str or not isinstance(date_str, str):
			return None
		date_str = date_str.strip()
			
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
		
		# ISO 8601 with fractional seconds and/or a UTC offset. Keep the wall-clock
		# time as sent (like the "Z" format above) so dates stay naive and local.
		try:
			parsed = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
			return parsed.replace(tzinfo=None)
		except ValueError:
			pass
				
		_LOGGER.warning(f"Failed to parse date: {date_str}")
		return None

	def _parse_time(self, time_str: Optional[str]) -> Optional[time]:
		"""Parse time string into time object.
		
		Args:
			time_str: Time string from API
			
		Returns:
			time object or None if parsing fails
		"""
		if not time_str or not isinstance(time_str, str):
			return None
			
		# Full timestamps (e.g. a lesson's "start") carry the time of day too
		if "T" in time_str or "-" in time_str:
			parsed = self._parse_date_or_none(time_str)
			return parsed.time() if parsed else None
			
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