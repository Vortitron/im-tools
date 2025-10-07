"""Persistent storage for InfoMentor integration."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "infomentor_cache"
DATA_RETENTION_DAYS = 14  # Keep data for 2 weeks


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
				}
			else:
				self._data = stored_data
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
		
		self._data["pupil_data"] = pupil_data
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
			last_update = datetime.fromisoformat(last_update_str)
			age = datetime.now() - last_update
			
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
		
		age = datetime.now() - last_update
		return age < timedelta(hours=max_age_hours)
	
	async def _cleanup_old_data(self) -> None:
		"""Remove data older than retention period."""
		if not self._data:
			return
		
		last_update_str = self._data.get("last_successful_update")
		if not last_update_str:
			return
		
		try:
			last_update = datetime.fromisoformat(last_update_str)
			age = datetime.now() - last_update
			
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
		}
		await self._store.async_save(self._data)
		_LOGGER.info("Cleared all stored data")

