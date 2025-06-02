"""Support for InfoMentor sensors."""

import logging
from datetime import datetime, time
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
	SENSOR_SCHEDULE,
	SENSOR_TODAY_SCHEDULE,
	SENSOR_HAS_SCHOOL_TODAY,
	SENSOR_HAS_PRESCHOOL_TODAY,
	ATTR_PUPIL_ID,
	ATTR_PUPIL_NAME,
	ATTR_AUTHOR,
	ATTR_PUBLISHED_DATE,
	ATTR_ENTRY_TYPE,
	ATTR_CONTENT,
	ATTR_START_TIME,
	ATTR_END_TIME,
	ATTR_SUBJECT,
	ATTR_TEACHER,
	ATTR_CLASSROOM,
	ATTR_SCHEDULE_TYPE,
	ATTR_STATUS,
	ATTR_EARLIEST_START,
	ATTR_LATEST_END,
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
			InfoMentorScheduleSensor(coordinator, config_entry, pupil_id),
			InfoMentorTodayScheduleSensor(coordinator, config_entry, pupil_id),
			InfoMentorHasSchoolTodaySensor(coordinator, config_entry, pupil_id),
			InfoMentorHasPreschoolTodaySensor(coordinator, config_entry, pupil_id),
			InfoMentorChildTypeSensor(coordinator, config_entry, pupil_id),
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


class InfoMentorScheduleSensor(InfoMentorPupilSensorBase):
	"""Sensor for pupil schedule (timetable and time registration)."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
		pupil_id: str,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator, config_entry, pupil_id)
		self._attr_name = f"{self.pupil_name} Schedule"
		self._attr_unique_id = f"{config_entry.entry_id}_{SENSOR_SCHEDULE}_{pupil_id}"
		self._attr_icon = "mdi:calendar-clock"
		
	@property
	def native_value(self) -> int:
		"""Return the number of schedule days."""
		schedule = self.coordinator.get_pupil_schedule(self.pupil_id)
		return len(schedule)
		
	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return additional state attributes."""
		attributes = {
			ATTR_PUPIL_ID: self.pupil_id,
			ATTR_PUPIL_NAME: self.pupil_name,
		}
		
		schedule = self.coordinator.get_pupil_schedule(self.pupil_id)
		if schedule:
			schedule_list = []
			for day in schedule[:7]:  # Limit to next 7 days
				day_info = {
					"date": day.date.strftime('%Y-%m-%d'),
					"weekday": day.date.strftime('%A'),
					"has_school": day.has_school,
					"has_preschool_or_fritids": day.has_preschool_or_fritids,
				}
				
				if day.earliest_start:
					day_info[ATTR_EARLIEST_START] = day.earliest_start.strftime('%H:%M')
				if day.latest_end:
					day_info[ATTR_LATEST_END] = day.latest_end.strftime('%H:%M')
					
				# Add timetable entries
				if day.timetable_entries:
					timetable = []
					for entry in day.timetable_entries:
						timetable.append({
							ATTR_SUBJECT: entry.subject,
							ATTR_START_TIME: entry.start_time.strftime('%H:%M'),
							ATTR_END_TIME: entry.end_time.strftime('%H:%M'),
							ATTR_TEACHER: entry.teacher,
							ATTR_CLASSROOM: entry.classroom,
						})
					day_info["timetable"] = timetable
					
				# Add time registrations
				if day.time_registrations:
					registrations = []
					for reg in day.time_registrations:
						reg_info = {
							ATTR_SCHEDULE_TYPE: reg.type,
							ATTR_STATUS: reg.status,
						}
						if reg.start_time:
							reg_info[ATTR_START_TIME] = reg.start_time.strftime('%H:%M')
						if reg.end_time:
							reg_info[ATTR_END_TIME] = reg.end_time.strftime('%H:%M')
						registrations.append(reg_info)
					day_info["time_registrations"] = registrations
					
				schedule_list.append(day_info)
				
			attributes["schedule_days"] = schedule_list
			
		return attributes


class InfoMentorTodayScheduleSensor(InfoMentorPupilSensorBase):
	"""Sensor for pupil's today schedule."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
		pupil_id: str,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator, config_entry, pupil_id)
		self._attr_name = f"{self.pupil_name} Today Schedule"
		self._attr_unique_id = f"{config_entry.entry_id}_{SENSOR_TODAY_SCHEDULE}_{pupil_id}"
		self._attr_icon = "mdi:calendar-today"
		
	@property
	def native_value(self) -> str:
		"""Return status of today's schedule."""
		today_schedule = self.coordinator.get_today_schedule(self.pupil_id)
		if not today_schedule:
			return "no_data"
		
		if today_schedule.has_school:
			return "school"
		elif today_schedule.has_preschool_or_fritids:
			return "preschool_fritids"
		else:
			return "no_activities"
		
	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return additional state attributes."""
		attributes = {
			ATTR_PUPIL_ID: self.pupil_id,
			ATTR_PUPIL_NAME: self.pupil_name,
		}
		
		today_schedule = self.coordinator.get_today_schedule(self.pupil_id)
		if today_schedule:
			attributes.update({
				"date": today_schedule.date.strftime('%Y-%m-%d'),
				"weekday": today_schedule.date.strftime('%A'),
				"has_school": today_schedule.has_school,
				"has_preschool_or_fritids": today_schedule.has_preschool_or_fritids,
			})
			
			if today_schedule.earliest_start:
				attributes[ATTR_EARLIEST_START] = today_schedule.earliest_start.strftime('%H:%M')
			if today_schedule.latest_end:
				attributes[ATTR_LATEST_END] = today_schedule.latest_end.strftime('%H:%M')
				
			# Add today's timetable
			if today_schedule.timetable_entries:
				timetable = []
				for entry in today_schedule.timetable_entries:
					timetable.append({
						ATTR_SUBJECT: entry.subject,
						ATTR_START_TIME: entry.start_time.strftime('%H:%M'),
						ATTR_END_TIME: entry.end_time.strftime('%H:%M'),
						ATTR_TEACHER: entry.teacher,
						ATTR_CLASSROOM: entry.classroom,
					})
				attributes["today_timetable"] = timetable
				
			# Add today's time registrations
			if today_schedule.time_registrations:
				registrations = []
				for reg in today_schedule.time_registrations:
					reg_info = {
						ATTR_SCHEDULE_TYPE: reg.type,
						ATTR_STATUS: reg.status,
					}
					if reg.start_time:
						reg_info[ATTR_START_TIME] = reg.start_time.strftime('%H:%M')
					if reg.end_time:
						reg_info[ATTR_END_TIME] = reg.end_time.strftime('%H:%M')
					registrations.append(reg_info)
				attributes["today_time_registrations"] = registrations
		
		return attributes


class InfoMentorHasSchoolTodaySensor(InfoMentorPupilSensorBase):
	"""Binary sensor for whether pupil has school today."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
		pupil_id: str,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator, config_entry, pupil_id)
		self._attr_name = f"{self.pupil_name} Has School Today"
		self._attr_unique_id = f"{config_entry.entry_id}_{SENSOR_HAS_SCHOOL_TODAY}_{pupil_id}"
		self._attr_icon = "mdi:school"
		
	@property
	def native_value(self) -> bool:
		"""Return whether pupil has school today."""
		return self.coordinator.has_school_today(self.pupil_id)
		
	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return additional state attributes."""
		attributes = {
			ATTR_PUPIL_ID: self.pupil_id,
			ATTR_PUPIL_NAME: self.pupil_name,
		}
		
		today_schedule = self.coordinator.get_today_schedule(self.pupil_id)
		if today_schedule and today_schedule.has_school:
			if today_schedule.earliest_start:
				attributes[ATTR_EARLIEST_START] = today_schedule.earliest_start.strftime('%H:%M')
			if today_schedule.latest_end:
				attributes[ATTR_LATEST_END] = today_schedule.latest_end.strftime('%H:%M')
				
		return attributes


class InfoMentorHasPreschoolTodaySensor(InfoMentorPupilSensorBase):
	"""Binary sensor for whether pupil has preschool/fritids today."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
		pupil_id: str,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator, config_entry, pupil_id)
		self._attr_name = f"{self.pupil_name} Has Preschool/Fritids Today"
		self._attr_unique_id = f"{config_entry.entry_id}_{SENSOR_HAS_PRESCHOOL_TODAY}_{pupil_id}"
		self._attr_icon = "mdi:human-child"
		
	@property
	def native_value(self) -> bool:
		"""Return whether pupil has preschool/fritids today."""
		return self.coordinator.has_preschool_or_fritids_today(self.pupil_id)
		
	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return additional state attributes."""
		attributes = {
			ATTR_PUPIL_ID: self.pupil_id,
			ATTR_PUPIL_NAME: self.pupil_name,
		}
		
		today_schedule = self.coordinator.get_today_schedule(self.pupil_id)
		if today_schedule and today_schedule.has_preschool_or_fritids:
			if today_schedule.earliest_start:
				attributes[ATTR_EARLIEST_START] = today_schedule.earliest_start.strftime('%H:%M')
			if today_schedule.latest_end:
				attributes[ATTR_LATEST_END] = today_schedule.latest_end.strftime('%H:%M')
				
		return attributes


class InfoMentorChildTypeSensor(InfoMentorPupilSensorBase):
	"""Sensor to determine child type and time registration based on timetable entries."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
		pupil_id: str,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator, config_entry, pupil_id)
		self._attr_name = f"{self.pupil_name} Child Type"
		self._attr_unique_id = f"{config_entry.entry_id}_child_type_{pupil_id}"
		self._attr_icon = "mdi:account-child"
		
	@property
	def native_value(self) -> str:
		"""Return child type based on timetable entries primarily, with time registration as fallback."""
		# Get schedule for the next few weeks to check for any timetable entries
		schedule_days = self.coordinator.get_schedule(self.pupil_id)
		
		if not schedule_days:
			return "unknown"
		
		# Primary check: If child has any timetable entries (school lessons), they're a school child
		has_any_timetable = any(day.has_school for day in schedule_days)
		
		if has_any_timetable:
			return "school"
		
		# Secondary check: Look at time registration types as fallback
		# This helps when timetable API isn't working properly
		time_reg_types = set()
		for day in schedule_days:
			for reg in day.time_registrations:
				time_reg_types.add(reg.type)
		
		# If we find explicit preschool registrations, this is a preschool child
		preschool_types = {"förskola", "forskola", "preschool"}
		if any(ptype in time_reg_types for ptype in preschool_types):
			return "preschool"
		
		# If we find fritids registrations without timetable entries, 
		# this is likely a school child whose timetable isn't available yet
		if "fritids" in time_reg_types:
			return "school"  # Fritids indicates school child
		
		# Default to preschool if no clear indicators
		return "preschool"
		
	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return additional state attributes."""
		attributes = {
			ATTR_PUPIL_ID: self.pupil_id,
			ATTR_PUPIL_NAME: self.pupil_name,
		}
		
		child_type = self.native_value
		
		# Set time registration type and description based on child type
		schedule_days = self.coordinator.get_schedule(self.pupil_id)
		has_any_timetable = any(day.has_school for day in schedule_days if day) if schedule_days else False
		
		# Get time registration types for better description
		time_reg_types = set()
		for day in schedule_days if schedule_days else []:
			for reg in day.time_registrations:
				time_reg_types.add(reg.type)
		
		if child_type == "school":
			attributes["time_registration_type"] = "Fritidsschema"
			if has_any_timetable:
				attributes["description"] = "Child has timetable entries → School child"
			else:
				attributes["description"] = "Determined as school child (but no timetable entries found)"
		elif child_type == "preschool":
			attributes["time_registration_type"] = "Förskola"
			if not time_reg_types:
				attributes["description"] = "No time registrations → Preschool child"
			elif any(ptype in time_reg_types for ptype in {"förskola", "forskola", "preschool"}):
				attributes["description"] = "Child has preschool time registrations → Preschool child"
			elif "fritids" in time_reg_types:
				attributes["description"] = "Child has fritids time registrations → School child (timetable API may not be working)"
			else:
				attributes["description"] = f"Time registration types: {list(time_reg_types)} → Preschool child"
		else:
			attributes["time_registration_type"] = "Unknown"
			attributes["description"] = "Unable to determine child type"
		
		# Add timetable statistics
		schedule_days = self.coordinator.get_schedule(self.pupil_id)
		if schedule_days:
			total_days_with_school = sum(1 for day in schedule_days if day.has_school)
			total_days_with_time_reg = sum(1 for day in schedule_days if day.has_preschool_or_fritids)
			
			attributes.update({
				"total_schedule_days": len(schedule_days),
				"days_with_school": total_days_with_school,
				"days_with_time_registration": total_days_with_time_reg,
			})
		
		return attributes 