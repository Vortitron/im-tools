"""The InfoMentor integration."""

import asyncio
import logging
from typing import Any, Dict
from datetime import datetime

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD, SERVICE_REFRESH_DATA, SERVICE_SWITCH_PUPIL
from .coordinator import InfoMentorDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Service schemas
SERVICE_REFRESH_DATA_SCHEMA = vol.Schema({
	vol.Optional("pupil_id"): str,
})

SERVICE_SWITCH_PUPIL_SCHEMA = vol.Schema({
	vol.Required("pupil_id"): str,
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
	"""Set up InfoMentor from a config entry."""
	_LOGGER.debug("Setting up InfoMentor integration")
	
	coordinator = InfoMentorDataUpdateCoordinator(
		hass,
		entry.data[CONF_USERNAME],
		entry.data[CONF_PASSWORD],
	)
	
	try:
		await coordinator.async_config_entry_first_refresh()
	except Exception as err:
		_LOGGER.error("Failed to authenticate with InfoMentor: %s", err)
		raise ConfigEntryNotReady from err
	
	hass.data.setdefault(DOMAIN, {})
	hass.data[DOMAIN][entry.entry_id] = coordinator
	
	# Set up platforms
	await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
	
	# Register device for the InfoMentor account
	device_registry = dr.async_get(hass)
	device_registry.async_get_or_create(
		config_entry_id=entry.entry_id,
		identifiers={(DOMAIN, entry.data[CONF_USERNAME])},
		manufacturer="InfoMentor",
		name=f"InfoMentor Account ({entry.data[CONF_USERNAME]})",
		model="Hub",
	)
	
	# Register services
	async def handle_refresh_data(call: ServiceCall) -> None:
		"""Handle refresh data service call."""
		# Check if we're in a backoff period
		if coordinator._should_backoff():
			backoff_time = coordinator._get_backoff_time()
			remaining_time = backoff_time - (datetime.now() - coordinator._last_auth_failure).total_seconds()
			_LOGGER.warning(f"Manual refresh blocked - in backoff period. {remaining_time:.0f} seconds remaining.")
			return
		
		pupil_id = call.data.get("pupil_id")
		if pupil_id:
			await coordinator.async_refresh_pupil_data(pupil_id)
		else:
			await coordinator.async_request_refresh()
	
	async def handle_switch_pupil(call: ServiceCall) -> None:
		"""Handle switch pupil service call."""
		pupil_id = call.data["pupil_id"]
		if coordinator.client:
			await coordinator.client.switch_pupil(pupil_id)
	
	hass.services.async_register(
		DOMAIN,
		SERVICE_REFRESH_DATA,
		handle_refresh_data,
		schema=SERVICE_REFRESH_DATA_SCHEMA,
	)
	
	hass.services.async_register(
		DOMAIN,
		SERVICE_SWITCH_PUPIL,
		handle_switch_pupil,
		schema=SERVICE_SWITCH_PUPIL_SCHEMA,
	)
	
	return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
	"""Unload a config entry."""
	_LOGGER.debug("Unloading InfoMentor integration")
	
	# Unload platforms
	unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
	
	if unload_ok:
		# Clean up coordinator
		coordinator: InfoMentorDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
		await coordinator.async_shutdown()
		
		# Remove from hass data
		hass.data[DOMAIN].pop(entry.entry_id)
		
		# Remove services if this was the last entry
		if not hass.data[DOMAIN]:
			hass.services.async_remove(DOMAIN, SERVICE_REFRESH_DATA)
			hass.services.async_remove(DOMAIN, SERVICE_SWITCH_PUPIL)
	
	return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
	"""Reload config entry."""
	await async_unload_entry(hass, entry)
	await async_setup_entry(hass, entry) 