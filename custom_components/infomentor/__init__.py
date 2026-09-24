"""The InfoMentor integration."""

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
	"""Set up InfoMentor from a config entry."""
	_LOGGER.debug("Setting up InfoMentor integration")
	
	# Lazy import to minimise import-time work
	from .coordinator import InfoMentorDataUpdateCoordinator
	
	coordinator = InfoMentorDataUpdateCoordinator(
		hass,
		entry.data[CONF_USERNAME],
		entry.data[CONF_PASSWORD],
		entry.entry_id,
	)
	
	try:
		# Add timeout protection for the first refresh
		await asyncio.wait_for(
			coordinator.async_config_entry_first_refresh(),
			timeout=120  # 2 minutes timeout
		)
	except asyncio.TimeoutError:
		_LOGGER.error("InfoMentor setup timed out after 2 minutes")
		raise ConfigEntryNotReady("Setup timeout") from None
	except asyncio.CancelledError:
		_LOGGER.error("InfoMentor setup was cancelled")
		raise ConfigEntryNotReady("Setup cancelled") from None
	except Exception as err:
		_LOGGER.error("Failed to authenticate with InfoMentor: %s", err)
		raise ConfigEntryNotReady from err
	
	hass.data.setdefault(DOMAIN, {})
	hass.data[DOMAIN][entry.entry_id] = coordinator
	
	# Entities have stable unique IDs, so existing registry entries (and any user
	# renames/areas) are reused. Use the cleanup_duplicate_entities service for
	# leftovers from old versions.
	
	# Set up platforms with timeout protection
	try:
		await asyncio.wait_for(
			hass.config_entries.async_forward_entry_setups(entry, PLATFORMS),
			timeout=60  # 1 minute for platform setup
		)
	except asyncio.TimeoutError:
		_LOGGER.error("Platform setup timed out after 1 minute")
		raise ConfigEntryNotReady("Platform setup timeout") from None
	except asyncio.CancelledError:
		_LOGGER.error("Platform setup was cancelled")
		raise ConfigEntryNotReady("Platform setup cancelled") from None
	
	# Register device for the InfoMentor account
	device_registry = dr.async_get(hass)
	device_registry.async_get_or_create(
		config_entry_id=entry.entry_id,
		identifiers={(DOMAIN, entry.data[CONF_USERNAME])},
		manufacturer="InfoMentor",
		name=f"InfoMentor Account ({entry.data[CONF_USERNAME]})",
		model="Hub",
	)
	
	await async_register_services(hass)
	
	coordinator.async_start_timers()
	
	return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
	"""Unload a config entry."""
	_LOGGER.debug("Unloading InfoMentor integration")
	
	# Unload platforms
	unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
	
	if unload_ok:
		# Clean up coordinator
		from .coordinator import InfoMentorDataUpdateCoordinator
		coordinator: InfoMentorDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
		await coordinator.async_shutdown()
		
		# Remove from hass data
		hass.data[DOMAIN].pop(entry.entry_id)
		
		# Remove services if this was the last entry
		if not hass.data[DOMAIN]:
			await async_unregister_services(hass)
	
	return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
	"""Reload config entry."""
	await async_unload_entry(hass, entry)
	await async_setup_entry(hass, entry) 