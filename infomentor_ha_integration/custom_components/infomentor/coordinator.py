"""DataUpdateCoordinator for InfoMentor."""

import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

# We need to add the infomentor library to the Python path
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from infomentor import InfoMentorClient, InfoMentorAuthError, InfoMentorConnectionError
from infomentor.models import NewsItem, TimelineEntry, PupilInfo

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
		
		super().__init__(
			hass,
			_LOGGER,
			name=DOMAIN,
			update_interval=DEFAULT_UPDATE_INTERVAL,
		)
		
	async def _async_update_data(self) -> Dict[str, Any]:
		"""Update data via library."""
		try:
			if not self.client:
				await self._setup_client()
				
			data = {}
			
			# Get data for each pupil
			for pupil_id in self.pupil_ids:
				pupil_data = await self._get_pupil_data(pupil_id)
				data[pupil_id] = pupil_data
				
			return data
			
		except InfoMentorAuthError as err:
			raise ConfigEntryAuthFailed from err
		except InfoMentorConnectionError as err:
			raise UpdateFailed(f"Error communicating with InfoMentor: {err}") from err
		except Exception as err:
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
		}
		
		try:
			# Get news
			news_items = await self.client.get_news(pupil_id)
			pupil_data["news"] = news_items
			_LOGGER.debug(f"Retrieved {len(news_items)} news items for pupil {pupil_id}")
			
		except Exception as err:
			_LOGGER.warning(f"Failed to get news for pupil {pupil_id}: {err}")
			
		try:
			# Get timeline
			timeline_entries = await self.client.get_timeline(pupil_id)
			pupil_data["timeline"] = timeline_entries
			_LOGGER.debug(f"Retrieved {len(timeline_entries)} timeline entries for pupil {pupil_id}")
			
		except Exception as err:
			_LOGGER.warning(f"Failed to get timeline for pupil {pupil_id}: {err}")
			
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