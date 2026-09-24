"""Support for InfoMentor button entities."""

from __future__ import annotations

import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
	BUTTON_DIAGNOSTICS_FULL,
	BUTTON_DIAGNOSTICS_REFRESH,
	BUTTON_TEST_NOTIFICATION,
	CONF_USERNAME,
	DOMAIN,
)
from .coordinator import InfoMentorDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
	hass: HomeAssistant,
	config_entry: ConfigEntry,
	async_add_entities: AddEntitiesCallback,
) -> None:
	"""Set up InfoMentor button entities."""
	coordinator: InfoMentorDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
	async_add_entities(
		[
			InfoMentorDiagnosticsButton(coordinator, config_entry, clear_cache=False),
			InfoMentorDiagnosticsButton(coordinator, config_entry, clear_cache=True),
			InfoMentorTestNotificationButton(coordinator, config_entry),
		],
		update_before_add=False,
	)


class InfoMentorDiagnosticsButton(CoordinatorEntity, ButtonEntity):
	"""Button to run an immediate diagnostics refresh (re-login + data fetch)."""

	def __init__(
		self,
		coordinator: InfoMentorDataUpdateCoordinator,
		config_entry: ConfigEntry,
		*,
		clear_cache: bool,
	) -> None:
		"""Initialise the button."""
		super().__init__(coordinator)
		self.config_entry = config_entry
		self._clear_cache = clear_cache
		# Full explicit names — do not use has_entity_name + translation_key here; HA was
		# only showing the device title for both buttons, so they looked identical.
		self._attr_has_entity_name = False
		self._attr_entity_category = EntityCategory.CONFIG
		if clear_cache:
			self._attr_name = "InfoMentor full refresh (clears schedule cache)"
			self._attr_unique_id = f"{config_entry.entry_id}_{BUTTON_DIAGNOSTICS_FULL}"
			self._attr_icon = "mdi:refresh-circle"
		else:
			self._attr_name = "InfoMentor run diagnostics"
			self._attr_unique_id = f"{config_entry.entry_id}_{BUTTON_DIAGNOSTICS_REFRESH}"
			self._attr_icon = "mdi:stethoscope"
		self._attr_device_info = DeviceInfo(
			identifiers={(DOMAIN, config_entry.data[CONF_USERNAME])},
			manufacturer="InfoMentor",
			name=f"InfoMentor Account ({config_entry.data[CONF_USERNAME]})",
			model="Hub",
		)

	async def async_press(self) -> None:
		"""Run diagnostics poke when the button is pressed."""
		try:
			await self.coordinator.async_diagnostic_poke(clear_cache=self._clear_cache)
		except Exception as err:
			_LOGGER.error("Diagnostics button failed: %s", err)
			raise


class InfoMentorTestNotificationButton(CoordinatorEntity, ButtonEntity):
	"""Button that pushes the latest InfoMentor notification to the configured targets."""

	def __init__(self, coordinator: InfoMentorDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
		"""Initialise the button."""
		super().__init__(coordinator)
		self._attr_has_entity_name = False
		self._attr_entity_category = EntityCategory.CONFIG
		self._attr_name = "InfoMentor send test notification"
		self._attr_unique_id = f"{config_entry.entry_id}_{BUTTON_TEST_NOTIFICATION}"
		self._attr_icon = "mdi:bell-ring"
		self._attr_device_info = DeviceInfo(
			identifiers={(DOMAIN, config_entry.data[CONF_USERNAME])},
			manufacturer="InfoMentor",
			name=f"InfoMentor Account ({config_entry.data[CONF_USERNAME]})",
			model="Hub",
		)

	async def async_press(self) -> None:
		"""Send the test notification; errors are shown in the UI."""
		await self.coordinator.async_send_test_notification()
