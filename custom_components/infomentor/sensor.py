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
	SENSOR_TOMORROW_SCHEDULE,
	SENSOR_HAS_SCHOOL_TODAY,
	SENSOR_HAS_PRESCHOOL_TODAY,
	SENSOR_HAS_SCHOOL_TOMORROW,
	SENSOR_DASHBOARD,
	SENSOR_DATA_FRESHNESS,
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
	try:
		coordinator: InfoMentorDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
		
		entities: List[SensorEntity] = []
		
		# Add a general pupil count sensor
		entities.append(InfoMentorPupilCountSensor(coordinator, config_entry))
		
		# Add a dashboard sensor that shows all kids
		entities.append(InfoMentorDashboardSensor(coordinator, config_entry))
		
		# Add a data freshness sensor
		entities.append(InfoMentorDataFreshnessSensor(coordinator, config_entry))
		
		# Add sensors for each pupil
		for pupil_id in coordinator.pupil_ids:
			try:
				entities.extend([
					InfoMentorNewsSensor(coordinator, config_entry, pupil_id),
					InfoMentorTimelineSensor(coordinator, config_entry, pupil_id),
					InfoMentorScheduleSensor(coordinator, config_entry, pupil_id),
					InfoMentorTodayScheduleSensor(coordinator, config_entry, pupil_id),
					InfoMentorTomorrowScheduleSensor(coordinator, config_entry, pupil_id),
					InfoMentorHasSchoolTodaySensor(coordinator, config_entry, pupil_id),
					InfoMentorHasSchoolTomorrowSensor(coordinator, config_entry, pupil_id),
					InfoMentorHasPreschoolTodaySensor(coordinator, config_entry, pupil_id),
					InfoMentorChildTypeSensor(coordinator, config_entry, pupil_id),
				])
			except Exception as e:
				_LOGGER.error(f"Failed to create sensors for pupil {pupil_id}: {e}")
				# Continue with other pupils
		
		_LOGGER.info(f"Setting up {len(entities)} InfoMentor entities")
		async_add_entities(entities, True)
		
	except Exception as e:
		_LOGGER.error(f"Failed to set up InfoMentor sensors: {e}")
		raise


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


class InfoMentorDataFreshnessSensor(InfoMentorSensorBase):
	"""Sensor showing when data was last successfully updated."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator, config_entry)
		self._attr_name = "InfoMentor Data Freshness"
		self._attr_unique_id = f"{config_entry.entry_id}_{SENSOR_DATA_FRESHNESS}"
		self._attr_icon = "mdi:update"
		self._attr_device_class = SensorDeviceClass.TIMESTAMP
		
	@property
	def native_value(self) -> Optional[datetime]:
		"""Return the timestamp of last successful update."""
		if self.coordinator._last_successful_update:
			# Ensure timezone-aware datetime for Home Assistant
			dt = self.coordinator._last_successful_update
			if dt.tzinfo is None:
				# Add UTC timezone if naive
				from datetime import timezone
				return dt.replace(tzinfo=timezone.utc)
			return dt
		return None
		
	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return additional state attributes."""
		attributes = {
			"username": self.config_entry.data[CONF_USERNAME],
			"using_cached_data": self.coordinator._using_cached_data,
		}
		
		if self.coordinator._last_successful_update:
			from datetime import timezone
			now_utc = datetime.now(timezone.utc)
			# Ensure both datetimes are timezone-aware for subtraction
			last_update = self.coordinator._last_successful_update
			if last_update.tzinfo is None:
				last_update = last_update.replace(tzinfo=timezone.utc)
			age = now_utc - last_update
			attributes["data_age_hours"] = round(age.total_seconds() / 3600, 1)
			attributes["data_age_days"] = round(age.total_seconds() / 86400, 1)
			
			# Status indicator
			if age.total_seconds() < 3600:  # < 1 hour
				attributes["freshness_status"] = "excellent"
			elif age.total_seconds() < 86400:  # < 1 day
				attributes["freshness_status"] = "good"
			elif age.total_seconds() < 172800:  # < 2 days
				attributes["freshness_status"] = "fair"
			else:
				attributes["freshness_status"] = "stale"
		else:
			attributes["freshness_status"] = "unknown"
			
		return attributes


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
		_LOGGER.debug(f"Initialized sensor for pupil {pupil_id}, info available: {self._pupil_info is not None}")
	
		
	@property
	def pupil_name(self) -> str:
		"""Get the pupil name for entity names and display."""
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
							ATTR_START_TIME: entry.start_time.strftime('%H:%M') if entry.start_time else None,
							ATTR_END_TIME: entry.end_time.strftime('%H:%M') if entry.end_time else None,
							ATTR_TEACHER: entry.teacher,
							ATTR_CLASSROOM: entry.room,
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
						ATTR_START_TIME: entry.start_time.strftime('%H:%M') if entry.start_time else None,
						ATTR_END_TIME: entry.end_time.strftime('%H:%M') if entry.end_time else None,
						ATTR_TEACHER: entry.teacher,
						ATTR_CLASSROOM: entry.room,
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
		self._attr_name = f"{self.pupil_name} Needs Preparation Today"
		self._attr_unique_id = f"{config_entry.entry_id}_{SENSOR_HAS_SCHOOL_TODAY}_{pupil_id}"
		self._attr_icon = "mdi:school"
		
	@property
	def native_value(self) -> bool:
		"""Return whether pupil has school today (including preschool/fritids)."""
		today_schedule = self.coordinator.get_cached_today_schedule(self.pupil_id)
		if not today_schedule:
			return False
		
		# Return true if they have school OR preschool/fritids - unified "needs preparation"
		return today_schedule.has_school or today_schedule.has_preschool_or_fritids
		
	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return additional state attributes."""
		attributes = {
			ATTR_PUPIL_ID: self.pupil_id,
			ATTR_PUPIL_NAME: self.pupil_name,
		}
		
		today_schedule = self.coordinator.get_cached_today_schedule(self.pupil_id)
		if today_schedule:
			attributes.update({
				"has_school": today_schedule.has_school,
				"has_preschool_or_fritids": today_schedule.has_preschool_or_fritids,
				"needs_preparation": today_schedule.has_school or today_schedule.has_preschool_or_fritids,
			})
			
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
		
		today_schedule = self.coordinator.get_cached_today_schedule(self.pupil_id)
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
		
		# Primary check: If child has any actual timetable entries (school lessons), they're a school child
		has_any_timetable = any(day.has_timetable_entries for day in schedule_days)
		
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
		has_any_timetable = any(day.has_timetable_entries for day in schedule_days if day) if schedule_days else False
		
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
			total_days_with_timetable = sum(1 for day in schedule_days if day.has_timetable_entries)
			total_days_with_school = sum(1 for day in schedule_days if day.has_school)
			total_days_with_time_reg = sum(1 for day in schedule_days if day.has_preschool_or_fritids)
			
			attributes.update({
				"total_schedule_days": len(schedule_days),
				"days_with_timetable": total_days_with_timetable,
				"days_with_school": total_days_with_school,
				"days_with_time_registration": total_days_with_time_reg,
			})
		
		return attributes


class InfoMentorDashboardSensor(InfoMentorSensorBase):
	"""Dashboard sensor that shows all kids and their schedules."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator, config_entry)
		self._attr_name = "InfoMentor Dashboard"
		self._attr_unique_id = f"{config_entry.entry_id}_{SENSOR_DASHBOARD}"
		self._attr_icon = "mdi:view-dashboard"
		
	@property
	def native_value(self) -> str:
		"""Return dashboard summary."""
		total_kids = len(self.coordinator.pupil_ids)
		kids_with_school_today = sum(1 for pupil_id in self.coordinator.pupil_ids 
									 if self.coordinator.has_school_today(pupil_id) or 
									    self.coordinator.has_preschool_or_fritids_today(pupil_id))
		kids_with_school_tomorrow = sum(1 for pupil_id in self.coordinator.pupil_ids 
										if self.coordinator.has_school_tomorrow(pupil_id) or 
										   self.coordinator.has_preschool_or_fritids_tomorrow(pupil_id))
		
		return f"{kids_with_school_today}/{total_kids} today, {kids_with_school_tomorrow}/{total_kids} tomorrow"
		
	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return additional state attributes."""
		attributes = {
			"username": self.config_entry.data[CONF_USERNAME],
			"total_kids": len(self.coordinator.pupil_ids),
			"kids": []
		}
		
		for pupil_id in self.coordinator.pupil_ids:
			pupil_info = self.coordinator.pupils_info.get(pupil_id)
			pupil_name = pupil_info.name if pupil_info and pupil_info.name else f"Pupil {pupil_id}"
			
			# Get today's schedule
			today_schedule = self.coordinator.get_today_schedule(pupil_id)
			tomorrow_schedule = self.coordinator.get_tomorrow_schedule(pupil_id)
			
			# Determine child type based on existing logic
			schedule_days = self.coordinator.get_schedule(pupil_id)
			has_any_timetable = any(day.has_timetable_entries for day in schedule_days) if schedule_days else False
			
			# Get time registration types
			time_reg_types = set()
			for day in schedule_days if schedule_days else []:
				for reg in day.time_registrations:
					time_reg_types.add(reg.type)
			
			if has_any_timetable:
				child_type = "school"
			elif any(ptype in time_reg_types for ptype in {"förskola", "forskola", "preschool"}):
				child_type = "preschool"
			elif "fritids" in time_reg_types:
				child_type = "school"
			else:
				child_type = "preschool"
			
			# Today's status
			today_has_school = today_schedule.has_school if today_schedule else False
			today_has_preschool_fritids = today_schedule.has_preschool_or_fritids if today_schedule else False
			today_needs_preparation = today_has_school or today_has_preschool_fritids
			
			# Tomorrow's status
			tomorrow_has_school = tomorrow_schedule.has_school if tomorrow_schedule else False
			tomorrow_has_preschool_fritids = tomorrow_schedule.has_preschool_or_fritids if tomorrow_schedule else False
			tomorrow_needs_preparation = tomorrow_has_school or tomorrow_has_preschool_fritids
			
			# Build today's schedule summary
			today_summary = "No school/care"
			if today_schedule:
				schedule_parts = []
				if today_schedule.has_school:
					schedule_parts.append("School")
				if today_schedule.has_preschool_or_fritids:
					if child_type == "school":
						schedule_parts.append("Fritids")
					else:
						schedule_parts.append("Preschool")
				
				if schedule_parts:
					today_summary = " + ".join(schedule_parts)
					if today_schedule.earliest_start and today_schedule.latest_end:
						today_summary += f" ({today_schedule.earliest_start.strftime('%H:%M')}-{today_schedule.latest_end.strftime('%H:%M')})"
			
			# Build tomorrow's schedule summary
			tomorrow_summary = "No school/care"
			if tomorrow_schedule:
				schedule_parts = []
				if tomorrow_schedule.has_school:
					schedule_parts.append("School")
				if tomorrow_schedule.has_preschool_or_fritids:
					if child_type == "school":
						schedule_parts.append("Fritids")
					else:
						schedule_parts.append("Preschool")
				
				if schedule_parts:
					tomorrow_summary = " + ".join(schedule_parts)
					if tomorrow_schedule.earliest_start and tomorrow_schedule.latest_end:
						tomorrow_summary += f" ({tomorrow_schedule.earliest_start.strftime('%H:%M')}-{tomorrow_schedule.latest_end.strftime('%H:%M')})"
			
			kid_info = {
				"pupil_id": pupil_id,
				"name": pupil_name,
				"child_type": child_type,
				"today": {
					"needs_preparation": today_needs_preparation,
					"has_school": today_has_school,
					"has_preschool_fritids": today_has_preschool_fritids,
					"summary": today_summary,
					"earliest_start": today_schedule.earliest_start.strftime('%H:%M') if today_schedule and today_schedule.earliest_start else None,
					"latest_end": today_schedule.latest_end.strftime('%H:%M') if today_schedule and today_schedule.latest_end else None
				},
				"tomorrow": {
					"needs_preparation": tomorrow_needs_preparation,
					"has_school": tomorrow_has_school,
					"has_preschool_fritids": tomorrow_has_preschool_fritids,
					"summary": tomorrow_summary,
					"earliest_start": tomorrow_schedule.earliest_start.strftime('%H:%M') if tomorrow_schedule and tomorrow_schedule.earliest_start else None,
					"latest_end": tomorrow_schedule.latest_end.strftime('%H:%M') if tomorrow_schedule and tomorrow_schedule.latest_end else None
				}
			}
			
			attributes["kids"].append(kid_info)
			
		return attributes


class InfoMentorTomorrowScheduleSensor(InfoMentorPupilSensorBase):
	"""Sensor for pupil's tomorrow schedule."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
		pupil_id: str,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator, config_entry, pupil_id)
		self._attr_name = f"{self.pupil_name} Tomorrow Schedule"
		self._attr_unique_id = f"{config_entry.entry_id}_{SENSOR_TOMORROW_SCHEDULE}_{pupil_id}"
		self._attr_icon = "mdi:calendar-tomorrow"
		
	@property
	def native_value(self) -> str:
		"""Return tomorrow's schedule summary."""
		tomorrow_schedule = self.coordinator.get_tomorrow_schedule(self.pupil_id)
		
		if not tomorrow_schedule:
			return "No schedule"
		
		# Determine child type for better display
		schedule_days = self.coordinator.get_schedule(self.pupil_id)
		has_any_timetable = any(day.has_timetable_entries for day in schedule_days) if schedule_days else False
		
		time_reg_types = set()
		for day in schedule_days if schedule_days else []:
			for reg in day.time_registrations:
				time_reg_types.add(reg.type)
		
		if has_any_timetable:
			child_type = "school"
		elif any(ptype in time_reg_types for ptype in {"förskola", "forskola", "preschool"}):
			child_type = "preschool"
		elif "fritids" in time_reg_types:
			child_type = "school"
		else:
			child_type = "preschool"
		
		schedule_parts = []
		if tomorrow_schedule.has_school:
			schedule_parts.append("School")
		if tomorrow_schedule.has_preschool_or_fritids:
			if child_type == "school":
				schedule_parts.append("Fritids")
			else:
				schedule_parts.append("Preschool")
		
		if not schedule_parts:
			return "No school/care"
		
		summary = " + ".join(schedule_parts)
		if tomorrow_schedule.earliest_start and tomorrow_schedule.latest_end:
			summary += f" ({tomorrow_schedule.earliest_start.strftime('%H:%M')}-{tomorrow_schedule.latest_end.strftime('%H:%M')})"
		
		return summary
		
	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return additional state attributes."""
		attributes = {
			ATTR_PUPIL_ID: self.pupil_id,
			ATTR_PUPIL_NAME: self.pupil_name,
		}
		
		tomorrow_schedule = self.coordinator.get_tomorrow_schedule(self.pupil_id)
		if tomorrow_schedule:
			attributes.update({
				"has_school": tomorrow_schedule.has_school,
				"has_preschool_or_fritids": tomorrow_schedule.has_preschool_or_fritids,
				"needs_preparation": tomorrow_schedule.has_school or tomorrow_schedule.has_preschool_or_fritids,
				"date": tomorrow_schedule.date.strftime('%Y-%m-%d'),
			})
			
			if tomorrow_schedule.earliest_start:
				attributes[ATTR_EARLIEST_START] = tomorrow_schedule.earliest_start.strftime('%H:%M')
			if tomorrow_schedule.latest_end:
				attributes[ATTR_LATEST_END] = tomorrow_schedule.latest_end.strftime('%H:%M')
			
			# Add tomorrow's timetable entries
			if tomorrow_schedule.timetable_entries:
				timetable = []
				for entry in tomorrow_schedule.timetable_entries:
					entry_info = {
						ATTR_SUBJECT: entry.subject,
						ATTR_START_TIME: entry.start_time.strftime('%H:%M'),
						ATTR_END_TIME: entry.end_time.strftime('%H:%M'),
					}
					if entry.teacher:
						entry_info[ATTR_TEACHER] = entry.teacher
					if entry.room:
						entry_info[ATTR_CLASSROOM] = entry.room
					timetable.append(entry_info)
				attributes["tomorrow_timetable"] = timetable
				
			# Add tomorrow's time registrations
			if tomorrow_schedule.time_registrations:
				registrations = []
				for reg in tomorrow_schedule.time_registrations:
					reg_info = {
						ATTR_SCHEDULE_TYPE: reg.type,
						ATTR_STATUS: reg.status,
					}
					if reg.start_time:
						reg_info[ATTR_START_TIME] = reg.start_time.strftime('%H:%M')
					if reg.end_time:
						reg_info[ATTR_END_TIME] = reg.end_time.strftime('%H:%M')
					registrations.append(reg_info)
				attributes["tomorrow_time_registrations"] = registrations
		
		return attributes


class InfoMentorHasSchoolTomorrowSensor(InfoMentorPupilSensorBase):
	"""Binary sensor for whether pupil has school tomorrow."""
	
	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
		pupil_id: str,
	) -> None:
		"""Initialise the sensor."""
		super().__init__(coordinator, config_entry, pupil_id)
		self._attr_name = f"{self.pupil_name} Has School Tomorrow"
		self._attr_unique_id = f"{config_entry.entry_id}_{SENSOR_HAS_SCHOOL_TOMORROW}_{pupil_id}"
		self._attr_icon = "mdi:school"
		
	@property
	def native_value(self) -> bool:
		"""Return whether pupil has school tomorrow (including preschool/fritids)."""
		tomorrow_schedule = self.coordinator.get_tomorrow_schedule(self.pupil_id)
		if not tomorrow_schedule:
			return False
		
		# Return true if they have school OR preschool/fritids - unified "needs preparation"
		return tomorrow_schedule.has_school or tomorrow_schedule.has_preschool_or_fritids
		
	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return additional state attributes."""
		attributes = {
			ATTR_PUPIL_ID: self.pupil_id,
			ATTR_PUPIL_NAME: self.pupil_name,
		}
		
		tomorrow_schedule = self.coordinator.get_tomorrow_schedule(self.pupil_id)
		if tomorrow_schedule:
			attributes.update({
				"has_school": tomorrow_schedule.has_school,
				"has_preschool_or_fritids": tomorrow_schedule.has_preschool_or_fritids,
				"needs_preparation": tomorrow_schedule.has_school or tomorrow_schedule.has_preschool_or_fritids,
				"date": tomorrow_schedule.date.strftime('%Y-%m-%d'),
			})
			
			if tomorrow_schedule.earliest_start:
				attributes[ATTR_EARLIEST_START] = tomorrow_schedule.earliest_start.strftime('%H:%M')
			if tomorrow_schedule.latest_end:
				attributes[ATTR_LATEST_END] = tomorrow_schedule.latest_end.strftime('%H:%M')
				
		return attributes 