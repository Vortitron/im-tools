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

from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD, SERVICE_REFRESH_DATA, SERVICE_SWITCH_PUPIL, SERVICE_FORCE_REFRESH, SERVICE_DEBUG_AUTH, SERVICE_CLEANUP_DUPLICATES

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Service schemas
SERVICE_REFRESH_DATA_SCHEMA = vol.Schema({
	vol.Optional("pupil_id"): str,
})

SERVICE_SWITCH_PUPIL_SCHEMA = vol.Schema({
	vol.Required("pupil_id"): str,
})

SERVICE_FORCE_REFRESH_SCHEMA = vol.Schema({
	vol.Optional("clear_cache", default=True): bool,
})

SERVICE_DEBUG_AUTH_SCHEMA = vol.Schema({})

SERVICE_CLEANUP_DUPLICATES_SCHEMA = vol.Schema({
	vol.Optional("dry_run", default=False): bool,
})


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
		
		# Group by unique_id to find duplicates
		unique_id_groups = {}
		for entity_id, reg_entry in infomentor_entities:
			unique_id = reg_entry.unique_id
			if unique_id not in unique_id_groups:
				unique_id_groups[unique_id] = []
			unique_id_groups[unique_id].append((entity_id, reg_entry))
		
		# Clean up duplicates, preferring entities without _2, _3 suffix
		duplicates_to_remove = []
		for unique_id, entity_group in unique_id_groups.items():
			if len(entity_group) > 1:
				# Sort to prefer entities without _2, _3 suffix
				entity_group.sort(key=lambda x: (
					'_2' in x[0] or '_3' in x[0] or '_4' in x[0] or '_5' in x[0],  # Put suffixed entities last
					x[0]  # Then sort alphabetically
				))
				
				# Keep the first one (original without suffix), mark the rest for removal
				to_keep = entity_group[0]
				to_remove = entity_group[1:]
				
				_LOGGER.debug(f"Unique ID {unique_id}: keeping {to_keep[0]}, removing {len(to_remove)} duplicates")
				duplicates_to_remove.extend([entity_id for entity_id, _ in to_remove])
		
		# Remove duplicates in batch
		for entity_id in duplicates_to_remove:
			entity_registry.async_remove(entity_id)
		
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
	
	# Clean up duplicate entities before setting up platforms (optional, for stability)
	cleanup_enabled = False  # Temporarily disabled to test if causing cancellation issues
	if cleanup_enabled:
		try:
			await asyncio.wait_for(
				_cleanup_duplicate_entities_before_setup(hass, entry),
				timeout=15  # Reduced to 15 seconds for cleanup
			)
		except asyncio.TimeoutError:
			_LOGGER.warning("Entity cleanup timed out, proceeding with setup")
		except Exception as e:
			_LOGGER.warning(f"Entity cleanup failed: {e}, proceeding with setup")
	else:
		_LOGGER.debug("Entity cleanup disabled, skipping")
	
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
	
	async def handle_force_refresh(call: ServiceCall) -> None:
		"""Handle force refresh service call."""
		clear_cache = call.data.get("clear_cache", True)
		await coordinator.force_refresh(clear_cache)
	
	async def handle_debug_auth(call: ServiceCall) -> None:
		"""Handle debug authentication service call."""
		debug_info = await coordinator.debug_authentication()
		_LOGGER.info(f"Debug authentication result: {debug_info}")
	
	async def handle_cleanup_duplicates(call: ServiceCall) -> None:
		"""Handle cleanup duplicate entities service call."""
		from homeassistant.helpers import entity_registry as er
		
		dry_run = call.data.get("dry_run", False)
		entity_registry = er.async_get(hass)
		
		# Find all InfoMentor entities
		infomentor_entities = []
		for entity_id, entry in entity_registry.entities.items():
			if entry.platform == DOMAIN:
				infomentor_entities.append((entity_id, entry))
		
		_LOGGER.info(f"Found {len(infomentor_entities)} InfoMentor entities")
		
		# Group by unique_id to find duplicates
		unique_id_groups = {}
		for entity_id, entry in infomentor_entities:
			unique_id = entry.unique_id
			if unique_id not in unique_id_groups:
				unique_id_groups[unique_id] = []
			unique_id_groups[unique_id].append((entity_id, entry))
		
		# Find and remove duplicates
		duplicates_removed = 0
		for unique_id, entity_group in unique_id_groups.items():
			if len(entity_group) > 1:
				# Sort to prefer entities without _2, _3 suffix
				entity_group.sort(key=lambda x: (
					'_2' in x[0] or '_3' in x[0] or '_4' in x[0],  # Put suffixed entities last
					x[0]  # Then sort alphabetically
				))
				
				# Keep the first one (original without suffix), remove the rest
				to_keep = entity_group[0]
				to_remove = entity_group[1:]
				
				_LOGGER.info(f"Unique ID {unique_id}: keeping {to_keep[0]}, removing {[e[0] for e in to_remove]}")
				
				if not dry_run:
					for entity_id, entry in to_remove:
						entity_registry.async_remove(entity_id)
						duplicates_removed += 1
						_LOGGER.info(f"Removed duplicate entity: {entity_id}")
				else:
					duplicates_removed += len(to_remove)
					_LOGGER.info(f"DRY RUN: Would remove {len(to_remove)} entities")
		
		if dry_run:
			_LOGGER.info(f"DRY RUN: Would remove {duplicates_removed} duplicate entities")
		else:
			_LOGGER.info(f"Removed {duplicates_removed} duplicate entities")
			if duplicates_removed > 0:
				_LOGGER.info("Please restart Home Assistant to see the changes")
	
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
	
	hass.services.async_register(
		DOMAIN,
		SERVICE_FORCE_REFRESH,
		handle_force_refresh,
		schema=SERVICE_FORCE_REFRESH_SCHEMA,
	)
	
	hass.services.async_register(
		DOMAIN,
		SERVICE_DEBUG_AUTH,
		handle_debug_auth,
		schema=SERVICE_DEBUG_AUTH_SCHEMA,
	)
	
	hass.services.async_register(
		DOMAIN,
		SERVICE_CLEANUP_DUPLICATES,
		handle_cleanup_duplicates,
		schema=SERVICE_CLEANUP_DUPLICATES_SCHEMA,
	)
	
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
			hass.services.async_remove(DOMAIN, SERVICE_REFRESH_DATA)
			hass.services.async_remove(DOMAIN, SERVICE_SWITCH_PUPIL)
			hass.services.async_remove(DOMAIN, SERVICE_FORCE_REFRESH)
			hass.services.async_remove(DOMAIN, SERVICE_DEBUG_AUTH)
	
	return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
	"""Reload config entry."""
	await async_unload_entry(hass, entry)
	await async_setup_entry(hass, entry) 