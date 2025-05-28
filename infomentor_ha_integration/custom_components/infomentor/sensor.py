"""Support for InfoMentor sensors."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
	DOMAIN,
	CONF_USERNAME,
	SENSOR_NEWS,
	SENSOR_TIMELINE,
	SENSOR_PUPIL_COUNT,
	ATTR_PUPIL_ID,
	ATTR_PUPIL_NAME,
	ATTR_AUTHOR,
	ATTR_PUBLISHED_DATE,
	ATTR_ENTRY_TYPE,
	ATTR_CONTENT,
)
from .coordinator import InfoMentorDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
	hass: HomeAssistant,
	config_entry: ConfigEntry,
	async_add_entities: AddEntitiesCallback,
) -> None:
	"""Set up InfoMentor sensors based on a config entry."""
	coordinator: InfoMentorDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
	
	entities: List[SensorEntity] = []
	
	# Add a general pupil count sensor
	entities.append(InfoMentorPupilCountSensor(coordinator, config_entry))
	
	# Add sensors for each pupil
	for pupil_id in coordinator.pupil_ids:
		entities.extend([
			InfoMentorNewsSensor(coordinator, config_entry, pupil_id),
			InfoMentorTimelineSensor(coordinator, config_entry, pupil_id),
		])
	
	async_add_entities(entities, True)


class InfoMentorSensorBase(CoordinatorEntity, SensorEntity):
	"""Base class for InfoMentor sensors."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator)
		self.config_entry = config_entry
		self._attr_device_info = DeviceInfo(
			identifiers={(DOMAIN, config_entry.data[CONF_USERNAME])},
			manufacturer="InfoMentor",
			name=f"InfoMentor Account ({config_entry.data[CONF_USERNAME]})",
			model="Hub",
		)


class InfoMentorPupilCountSensor(InfoMentorSensorBase):
	"""Sensor for total number of pupils."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator, config_entry)
		self._attr_name = "InfoMentor Pupil Count"
		self._attr_unique_id = f"{config_entry.entry_id}_{SENSOR_PUPIL_COUNT}"
		self._attr_icon = "mdi:account-group"
		
	@property
	def native_value(self) -> int:
		"""Return the number of pupils."""
		return len(self.coordinator.pupil_ids)
		
	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return additional state attributes."""
		return {
			"pupil_ids": self.coordinator.pupil_ids,
			"username": self.config_entry.data[CONF_USERNAME],
		}


class InfoMentorPupilSensorBase(InfoMentorSensorBase):
	"""Base class for pupil-specific sensors."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
		pupil_id: str,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator, config_entry)
		self.pupil_id = pupil_id
		self._pupil_info = coordinator.pupils_info.get(pupil_id)
		
	@property
	def pupil_name(self) -> str:
		"""Get the pupil name or ID."""
		if self._pupil_info and self._pupil_info.name:
			return self._pupil_info.name
		return f"Pupil {self.pupil_id}"
		
	@property
	def available(self) -> bool:
		"""Return if entity is available."""
		return (
			self.coordinator.last_update_success
			and self.coordinator.data is not None
			and self.pupil_id in self.coordinator.data
		)


class InfoMentorNewsSensor(InfoMentorPupilSensorBase):
	"""Sensor for pupil news items."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
		pupil_id: str,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator, config_entry, pupil_id)
		self._attr_name = f"{self.pupil_name} News"
		self._attr_unique_id = f"{config_entry.entry_id}_{SENSOR_NEWS}_{pupil_id}"
		self._attr_icon = "mdi:newspaper"
		self._attr_device_class = SensorDeviceClass.TIMESTAMP
		
	@property
	def native_value(self) -> int:
		"""Return the number of news items."""
		return self.coordinator.get_pupil_news_count(self.pupil_id)
		
	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return additional state attributes."""
		attributes = {
			ATTR_PUPIL_ID: self.pupil_id,
			ATTR_PUPIL_NAME: self.pupil_name,
		}
		
		# Add latest news item details
		latest_news = self.coordinator.get_latest_news_item(self.pupil_id)
		if latest_news:
			attributes.update({
				"latest_title": latest_news.title,
				"latest_content": latest_news.content[:200] + "..." if len(latest_news.content) > 200 else latest_news.content,
				ATTR_AUTHOR: latest_news.author,
				ATTR_PUBLISHED_DATE: latest_news.published_date.isoformat(),
			})
			
		# Add all news items (limited for performance)
		if self.coordinator.data and self.pupil_id in self.coordinator.data:
			news_items = self.coordinator.data[self.pupil_id].get("news", [])
			news_list = []
			for item in news_items[:10]:  # Limit to 10 most recent
				news_list.append({
					"id": item.id,
					"title": item.title,
					"published_date": item.published_date.isoformat(),
					"author": item.author,
				})
			attributes["news_items"] = news_list
			
		return attributes


class InfoMentorTimelineSensor(InfoMentorPupilSensorBase):
	"""Sensor for pupil timeline entries."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
		pupil_id: str,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator, config_entry, pupil_id)
		self._attr_name = f"{self.pupil_name} Timeline"
		self._attr_unique_id = f"{config_entry.entry_id}_{SENSOR_TIMELINE}_{pupil_id}"
		self._attr_icon = "mdi:timeline"
		self._attr_device_class = SensorDeviceClass.TIMESTAMP
		
	@property
	def native_value(self) -> int:
		"""Return the number of timeline entries."""
		return self.coordinator.get_pupil_timeline_count(self.pupil_id)
		
	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return additional state attributes."""
		attributes = {
			ATTR_PUPIL_ID: self.pupil_id,
			ATTR_PUPIL_NAME: self.pupil_name,
		}
		
		# Add latest timeline entry details
		latest_entry = self.coordinator.get_latest_timeline_entry(self.pupil_id)
		if latest_entry:
			attributes.update({
				"latest_title": latest_entry.title,
				"latest_content": latest_entry.content[:200] + "..." if len(latest_entry.content) > 200 else latest_entry.content,
				ATTR_ENTRY_TYPE: latest_entry.entry_type,
				ATTR_AUTHOR: latest_entry.author,
				"latest_date": latest_entry.date.isoformat(),
			})
			
		# Add all timeline entries (limited for performance)
		if self.coordinator.data and self.pupil_id in self.coordinator.data:
			timeline_entries = self.coordinator.data[self.pupil_id].get("timeline", [])
			timeline_list = []
			for entry in timeline_entries[:10]:  # Limit to 10 most recent
				timeline_list.append({
					"id": entry.id,
					"title": entry.title,
					"date": entry.date.isoformat(),
					"entry_type": entry.entry_type,
					"author": entry.author,
				})
			attributes["timeline_entries"] = timeline_list
			
		return attributes 