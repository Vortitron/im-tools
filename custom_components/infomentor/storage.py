"""Persistent storage for InfoMentor integration."""

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)


def _serialize_dataclass(obj: Any) -> Any:
	"""Recursively serialize dataclass objects to dicts with datetime/time conversion."""
	from datetime import datetime, time
	
	if is_dataclass(obj) and not isinstance(obj, type):
		# Convert dataclass to dict, then serialize nested objects
		obj_dict = asdict(obj)
		return _serialize_dataclass(obj_dict)
	elif isinstance(obj, datetime):
		return obj.isoformat()
	elif isinstance(obj, time):
		return obj.isoformat()
	elif isinstance(obj, list):
		return [_serialize_dataclass(item) for item in obj]
	elif isinstance(obj, dict):
		return {key: _serialize_dataclass(value) for key, value in obj.items()}
	else:
		return obj

STORAGE_VERSION = 1
STORAGE_KEY = "infomentor_cache"
DATA_RETENTION_DAYS = 14  # Keep data for 2 weeks
AUTH_COOKIE_KEY = "auth_cookies"
AUTH_COOKIE_TS_KEY = "auth_cookies_updated"


class InfoMentorStorage:
	"""Handles persistent storage of InfoMentor data."""
	
	def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
		"""Initialise storage handler."""
		self.hass = hass
		self.entry_id = entry_id
		self._store = Store(
			hass,
			STORAGE_VERSION,
			f"{STORAGE_KEY}_{entry_id}",
		)
		self._data: Optional[Dict[str, Any]] = None
		self._selected_school_url: Optional[str] = None
		
	async def async_load(self) -> Dict[str, Any]:
		"""Load cached data from storage."""
		if self._data is None:
			stored_data = await self._store.async_load()
			if stored_data is None:
				self._data = {
					"last_successful_update": None,
					"last_auth_success": None,
					"pupil_data": {},
					"pupil_ids": [],
					"pupil_names": {},
					"selected_school_url": None,
					"selected_school_name": None,
					AUTH_COOKIE_KEY: {},
					AUTH_COOKIE_TS_KEY: None,
				}
			else:
				self._data = stored_data
				self._data.setdefault("selected_school_url", None)
				self._data.setdefault("selected_school_name", None)
				self._data.setdefault(AUTH_COOKIE_KEY, {})
				self._data.setdefault(AUTH_COOKIE_TS_KEY, None)
				# Clean up old data
				await self._cleanup_old_data()
		
		return self._data
	
	async def async_save(
		self,
		pupil_data: Dict[str, Any],
		pupil_ids: list[str],
		pupil_names: Dict[str, str],
		last_update: Optional[datetime] = None,
		auth_success: bool = False,
	) -> None:
		"""Save data to persistent storage."""
		if self._data is None:
			await self.async_load()
		
		update_time = last_update or datetime.now()
		
		# Serialize dataclass objects to dicts for JSON storage
		serialized_pupil_data = _serialize_dataclass(pupil_data)
		
		self._data["pupil_data"] = serialized_pupil_data
		self._data["pupil_ids"] = pupil_ids
		self._data["pupil_names"] = pupil_names
		self._data["last_successful_update"] = update_time.isoformat()
		
		if auth_success:
			self._data["last_auth_success"] = update_time.isoformat()
		
		await self._store.async_save(self._data)
		_LOGGER.debug(f"Saved data to persistent storage (last update: {update_time})")
	
	async def get_cached_pupil_data(self) -> Optional[Dict[str, Any]]:
		"""Get cached pupil data if available and not too old."""
		if self._data is None:
			await self.async_load()
		
		pupil_data = self._data.get("pupil_data", {})
		last_update_str = self._data.get("last_successful_update")
		
		if not pupil_data or not last_update_str:
			return None
		
		# Check if data is too old
		try:
			from datetime import timezone
			last_update = datetime.fromisoformat(last_update_str)
			# Ensure timezone-aware for comparison
			if last_update.tzinfo is None:
				last_update = last_update.replace(tzinfo=timezone.utc)
			
			now_utc = datetime.now(timezone.utc)
			age = now_utc - last_update
			
			if age > timedelta(days=DATA_RETENTION_DAYS):
				_LOGGER.warning(f"Cached data is {age.days} days old, too stale to use")
				return None
			
			_LOGGER.info(f"Using cached data from {last_update} ({age.total_seconds() / 3600:.1f} hours ago)")
			return pupil_data
			
		except (ValueError, TypeError) as e:
			_LOGGER.error(f"Error parsing last update time: {e}")
			return None
	
	async def get_pupil_ids(self) -> list[str]:
		"""Get cached pupil IDs."""
		if self._data is None:
			await self.async_load()
		
		return self._data.get("pupil_ids", [])
	
	async def get_pupil_names(self) -> Dict[str, str]:
		"""Get cached pupil names."""
		if self._data is None:
			await self.async_load()
		
		return self._data.get("pupil_names", {})
	
	async def get_last_successful_update(self) -> Optional[datetime]:
		"""Get timestamp of last successful update."""
		if self._data is None:
			await self.async_load()
		
		last_update_str = self._data.get("last_successful_update")
		if not last_update_str:
			return None
		
		try:
			return datetime.fromisoformat(last_update_str)
		except (ValueError, TypeError):
			return None
	
	async def get_last_auth_success(self) -> Optional[datetime]:
		"""Get timestamp of last successful authentication."""
		if self._data is None:
			await self.async_load()
		
		last_auth_str = self._data.get("last_auth_success")
		if not last_auth_str:
			return None
		
		try:
			return datetime.fromisoformat(last_auth_str)
		except (ValueError, TypeError):
			return None
	
	async def has_recent_data(self, max_age_hours: int = 24) -> bool:
		"""Check if we have recent cached data."""
		last_update = await self.get_last_successful_update()
		if not last_update:
			return False
		
		from datetime import timezone
		# Ensure timezone-aware for comparison
		if last_update.tzinfo is None:
			last_update = last_update.replace(tzinfo=timezone.utc)
		
		now_utc = datetime.now(timezone.utc)
		age = now_utc - last_update
		return age < timedelta(hours=max_age_hours)
	
	async def _cleanup_old_data(self) -> None:
		"""Remove data older than retention period."""
		if not self._data:
			return
		
		last_update_str = self._data.get("last_successful_update")
		if not last_update_str:
			return
		
		try:
			from datetime import timezone
			last_update = datetime.fromisoformat(last_update_str)
			# Ensure timezone-aware for comparison
			if last_update.tzinfo is None:
				last_update = last_update.replace(tzinfo=timezone.utc)
			
			now_utc = datetime.now(timezone.utc)
			age = now_utc - last_update
			
			if age > timedelta(days=DATA_RETENTION_DAYS):
				_LOGGER.info(f"Cleaning up data older than {DATA_RETENTION_DAYS} days")
				self._data = {
					"last_successful_update": None,
					"last_auth_success": None,
					"pupil_data": {},
					"pupil_ids": [],
					"pupil_names": {},
				}
				await self._store.async_save(self._data)
		except (ValueError, TypeError) as e:
			_LOGGER.error(f"Error during cleanup: {e}")
	
	async def get_selected_school_url(self) -> Optional[str]:
		"""Get the previously selected school URL."""
		if self._data is None:
			await self.async_load()
		
		return self._data.get("selected_school_url")

	async def get_selected_school_details(self) -> tuple[Optional[str], Optional[str]]:
		"""Get the previously selected school URL and name."""
		if self._data is None:
			await self.async_load()
		
		return (
			self._data.get("selected_school_url"),
			self._data.get("selected_school_name"),
		)
	
	async def save_selected_school_url(self, school_url: str, school_name: str) -> None:
		"""Save the selected school URL for reuse."""
		if self._data is None:
			await self.async_load()
		
		self._data["selected_school_url"] = school_url
		self._data["selected_school_name"] = school_name
		await self._store.async_save(self._data)
		_LOGGER.info(f"Saved selected school: {school_name} -> {school_url}")
	
	async def clear(self) -> None:
		"""Clear all stored data."""
		self._data = {
			"last_successful_update": None,
			"last_auth_success": None,
			"pupil_data": {},
			"pupil_ids": [],
			"pupil_names": {},
			"selected_school_url": None,
			"selected_school_name": None,
			AUTH_COOKIE_KEY: {},
			AUTH_COOKIE_TS_KEY: None,
		}
		await self._store.async_save(self._data)
		_LOGGER.info("Cleared all stored data")

	async def save_auth_cookies(self, cookies: Dict[str, str]) -> None:
		"""Persist authentication cookies for session reuse."""
		if self._data is None:
			await self.async_load()
		
		from datetime import timezone
		now_utc = datetime.now(timezone.utc)
		
		self._data[AUTH_COOKIE_KEY] = cookies or {}
		self._data[AUTH_COOKIE_TS_KEY] = now_utc.isoformat()
		await self._store.async_save(self._data)
		_LOGGER.debug(f"Saved {len(cookies or {})} authentication cookies")

	async def get_auth_cookies(self) -> tuple[Dict[str, str], Optional[datetime]]:
		"""Return stored authentication cookies and the timestamp they were saved."""
		if self._data is None:
			await self.async_load()
		
		cookies = self._data.get(AUTH_COOKIE_KEY) or {}
		timestamp_str = self._data.get(AUTH_COOKIE_TS_KEY)
		timestamp = None
		if timestamp_str:
			try:
				timestamp = datetime.fromisoformat(timestamp_str)
			except (ValueError, TypeError):
				timestamp = None
		return cookies, timestamp

	async def clear_auth_cookies(self) -> None:
		"""Remove stored authentication cookies."""
		if self._data is None:
			await self.async_load()
		
		self._data[AUTH_COOKIE_KEY] = {}
		self._data[AUTH_COOKIE_TS_KEY] = None
		await self._store.async_save(self._data)
		_LOGGER.debug("Cleared stored authentication cookies")

