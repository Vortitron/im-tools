"""Support for InfoMentor binary sensors."""

import logging
from typing import Any, Dict, List

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
	DOMAIN,
	CONF_USERNAME,
	BINARY_SENSOR_PE_NEXT_SCHOOL_DAY,
	ATTR_PUPIL_ID,
	ATTR_PUPIL_NAME,
)
from .coordinator import InfoMentorDataUpdateCoordinator
from .school_data import kit_events, next_school_day, pe_lessons

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
	hass: HomeAssistant,
	config_entry: ConfigEntry,
	async_add_entities: AddEntitiesCallback,
) -> None:
	"""Set up InfoMentor binary sensors based on a config entry."""
	coordinator: InfoMentorDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
	async_add_entities(
		InfoMentorPENextSchoolDaySensor(coordinator, config_entry, pupil_id)
		for pupil_id in coordinator.pupil_ids
	)


class InfoMentorPENextSchoolDaySensor(CoordinatorEntity, BinarySensorEntity):
	"""On when the pupil's next school day has PE — time to pack the gym bag.

	Counts PE lessons in the timetable and calendar events such as "Idrott" or
	"Bad" (swimming), which some teachers only put in the calendar.
	"""

	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
		pupil_id: str,
	) -> None:
		"""Initialise the binary sensor."""
		super().__init__(coordinator)
		self.pupil_id = pupil_id
		pupil_info = coordinator.pupils_info.get(pupil_id)
		self.pupil_name = pupil_info.name if pupil_info and pupil_info.name else f"Pupil {pupil_id}"
		self._attr_name = f"{self.pupil_name} PE Next School Day"
		self._attr_unique_id = f"{config_entry.entry_id}_{BINARY_SENSOR_PE_NEXT_SCHOOL_DAY}_{pupil_id}"
		self._attr_icon = "mdi:run"
		self._attr_device_info = DeviceInfo(
			identifiers={(DOMAIN, config_entry.data[CONF_USERNAME])},
			manufacturer="InfoMentor",
			name=f"InfoMentor Account ({config_entry.data[CONF_USERNAME]})",
			model="Hub",
		)

	@property
	def available(self) -> bool:
		"""Return if entity is available."""
		return (
			self.coordinator.last_update_success
			and self.coordinator.data is not None
			and self.pupil_id in self.coordinator.data
		)

	def _next_day_and_pe(self) -> tuple[Any, List[Any], List[Dict[str, Any]]]:
		schedule = self.coordinator.get_pupil_schedule(self.pupil_id)
		day = next_school_day(schedule, dt_util.now().date())
		if day is None:
			return None, [], []
		events = kit_events(self.coordinator.get_pupil_calendar(self.pupil_id), day.date.date())
		return day, pe_lessons(day), events

	@property
	def is_on(self) -> bool:
		"""Return True if the next school day (after today) has PE or swimming."""
		_day, lessons, events = self._next_day_and_pe()
		return bool(lessons or events)

	@property
	def extra_state_attributes(self) -> Dict[str, Any]:
		"""Return the day checked, the PE lesson times and whether today has PE."""
		day, lessons, events = self._next_day_and_pe()
		today = self.coordinator.get_today_schedule(self.pupil_id)
		return {
			ATTR_PUPIL_ID: self.pupil_id,
			ATTR_PUPIL_NAME: self.pupil_name,
			"date": day.date.date().isoformat() if day else None,
			"times": [
				entry.start_time.strftime("%H:%M") for entry in lessons if entry.start_time
			],
			"events": [event.get("title") for event in events],
			"pe_today": bool(
				pe_lessons(today)
				or kit_events(self.coordinator.get_pupil_calendar(self.pupil_id), dt_util.now().date())
			),
		}
