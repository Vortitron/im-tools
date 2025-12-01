"""The InfoMentor integration."""

import asyncio
import logging
from typing import Any, Dict
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def _cleanup_duplicate_entities_before_setup(hass: HomeAssistant, entry: ConfigEntry) -> None:
	"""Clean up duplicate InfoMentor entities before setting up new ones."""
	from homeassistant.helpers import entity_registry as er
	
	try:
		entity_registry = er.async_get(hass)
		
		# Find all InfoMentor entities for this config entry
		infomentor_entities = []
		for entity_id, reg_entry in entity_registry.entities.items():
			if reg_entry.platform == DOMAIN and reg_entry.config_entry_id == entry.entry_id:
				infomentor_entities.append((entity_id, reg_entry))
		
		if not infomentor_entities:
			_LOGGER.debug("No existing InfoMentor entities found for cleanup")
			return
		
		_LOGGER.info(f"Found {len(infomentor_entities)} existing InfoMentor entities, checking for duplicates")
		
		# AGGRESSIVE CLEANUP: Remove ALL InfoMentor entities so new ones get original names
		# This ensures no conflicts with "unavailable" entities
		entities_to_remove = [entity_id for entity_id, _ in infomentor_entities]
		
		_LOGGER.info(f"AGGRESSIVE CLEANUP: Removing ALL {len(entities_to_remove)} InfoMentor entities to ensure clean setup")
		
		for entity_id in entities_to_remove:
			entity_registry.async_remove(entity_id)
			_LOGGER.debug(f"Removed entity for clean setup: {entity_id}")
		
		duplicates_to_remove = entities_to_remove  # For logging consistency
		
		if duplicates_to_remove:
			_LOGGER.info(f"Cleaned up {len(duplicates_to_remove)} duplicate entities before setup")
		else:
			_LOGGER.debug("No duplicate entities found to clean up")
			
	except Exception as e:
		_LOGGER.warning(f"Error during entity cleanup: {e}")
		# Don't let cleanup errors block the integration setup


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
	
	# IMPORTANT: Always clean up duplicate entities to ensure proper entity reuse
	# This prevents new _2, _3 entities from being created
	try:
		await asyncio.wait_for(
			_cleanup_duplicate_entities_before_setup(hass, entry),
			timeout=15  # 15 seconds for cleanup
		)
		_LOGGER.info("Duplicate entity cleanup completed - entities should reuse originals")
	except asyncio.TimeoutError:
		_LOGGER.warning("Entity cleanup timed out, proceeding with setup")
	except Exception as e:
		_LOGGER.warning(f"Entity cleanup failed: {e}, proceeding with setup")
	
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