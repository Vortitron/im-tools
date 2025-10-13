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

from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD, SERVICE_REFRESH_DATA, SERVICE_SWITCH_PUPIL, SERVICE_FORCE_REFRESH, SERVICE_DEBUG_AUTH, SERVICE_CLEANUP_DUPLICATES, SERVICE_RETRY_AUTH

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
	vol.Optional("aggressive_cleanup", default=False): bool,
})

SERVICE_RETRY_AUTH_SCHEMA = vol.Schema({
	vol.Optional("clear_cache", default=False): bool,
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
	
	# Register services
	async def handle_refresh_data(call: ServiceCall) -> None:
		"""Handle refresh data service call."""
		# Check if we're in a backoff period
		if coordinator._should_backoff():
			backoff_time = coordinator._get_backoff_time()
			_LOGGER.warning(f"Manual refresh blocked - in backoff period. {backoff_time:.0f} seconds remaining.")
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
		
		# Add option for aggressive cleanup
		aggressive_cleanup = call.data.get("aggressive_cleanup", False)
		if aggressive_cleanup:
			_LOGGER.info("AGGRESSIVE CLEANUP MODE: Will remove ALL InfoMentor entities")
			to_remove_batch = [entity_id for entity_id, _ in infomentor_entities]
			
			if not dry_run:
				for entity_id in to_remove_batch:
					entity_registry.async_remove(entity_id)
					duplicates_removed += 1
					_LOGGER.info(f"Removed entity for clean setup: {entity_id}")
			else:
				duplicates_removed = len(to_remove_batch)
				_LOGGER.info(f"DRY RUN: Would remove ALL {duplicates_removed} entities: {sorted(to_remove_batch)}")
			
			if dry_run:
				_LOGGER.info(f"DRY RUN: Would remove {duplicates_removed} entities")
			else:
				_LOGGER.info(f"Removed {duplicates_removed} entities")
				if duplicates_removed > 0:
					_LOGGER.info("Please restart Home Assistant to see the changes")
			return
		
		# Normal selective cleanup logic follows
		
		# Group by unique_id to find duplicates
		unique_id_groups = {}
		for entity_id, entry in infomentor_entities:
			unique_id = entry.unique_id
			if unique_id not in unique_id_groups:
				unique_id_groups[unique_id] = []
			unique_id_groups[unique_id].append((entity_id, entry))
		
		# First pass: prefer original entity_ids over suffixed variants
		base_groups: Dict[str, list[tuple[str, Any]]] = {}
		for entity_id, reg_entry in infomentor_entities:
			base_id = entity_id
			for n in range(2, 10):
				suffix = f"_{n}"
				if entity_id.endswith(suffix):
					base_id = entity_id[: -len(suffix)]
					break
			base_groups.setdefault(base_id, []).append((entity_id, reg_entry))

		duplicates_removed = 0
		to_remove_batch: list[str] = []
		for base_id, group in base_groups.items():
			if len(group) > 1 and any(eid == base_id for eid, _ in group):
				suffixed = [eid for eid, _ in group if eid != base_id]
				if suffixed:
					_LOGGER.info(f"Prefer original '{base_id}': removing {suffixed}")
					to_remove_batch.extend(suffixed)

		# Second pass: duplicates by unique_id
		for unique_id, entity_group in unique_id_groups.items():
			if len(entity_group) > 1:
				entity_group.sort(
					key=lambda x: (
						any(sfx in x[0] for sfx in [f"_{i}" for i in range(2, 10)]),
						len(x[0]),
						x[0],
					)
				)
				to_remove_batch.extend([eid for eid, _ in entity_group[1:]])

		# Apply removals and ensure originals are enabled
		if not dry_run:
			for entity_id in set(to_remove_batch):
				entity_registry.async_remove(entity_id)
				duplicates_removed += 1
				_LOGGER.info(f"Removed duplicate entity: {entity_id}")
			
			# Ensure original entities are enabled and properly configured
			for entity_id, reg_entry in infomentor_entities:
				if entity_id not in to_remove_batch:  # This is an original we're keeping
					updates = {}
					if reg_entry.disabled_by is not None:
						updates["disabled_by"] = None
						_LOGGER.info(f"Enabling original entity: {entity_id}")
					if reg_entry.hidden_by is not None:
						updates["hidden_by"] = None
						_LOGGER.info(f"Unhiding original entity: {entity_id}")
					if updates:
						entity_registry.async_update_entity(entity_id, **updates)
		else:
			duplicates_removed = len(set(to_remove_batch))
			_LOGGER.info(f"DRY RUN: Would remove {duplicates_removed} entities: {sorted(set(to_remove_batch))}")
			# In dry run, also show what would be enabled
			for entity_id, reg_entry in infomentor_entities:
				if entity_id not in to_remove_batch:
					if reg_entry.disabled_by is not None:
						_LOGGER.info(f"DRY RUN: Would enable original entity: {entity_id}")
					if reg_entry.hidden_by is not None:
						_LOGGER.info(f"DRY RUN: Would unhide original entity: {entity_id}")
		
		if dry_run:
			_LOGGER.info(f"DRY RUN: Would remove {duplicates_removed} duplicate entities")
		else:
			_LOGGER.info(f"Removed {duplicates_removed} duplicate entities")
			if duplicates_removed > 0:
				_LOGGER.info("Please restart Home Assistant to see the changes")
	
	async def handle_retry_auth(call: ServiceCall) -> None:
		"""Handle retry authentication service call."""
		clear_cache = call.data.get("clear_cache", False)
		_LOGGER.info(f"Manual authentication retry requested (clear_cache={clear_cache})")
		
		# Reset auth failure tracking to allow immediate retry
		coordinator._auth_failure_count = 0
		coordinator._last_auth_failure = None
		coordinator._last_auth_check = None
		
		if clear_cache:
			# Clear cached data to force fresh authentication
			coordinator.data = None
			coordinator._using_cached_data = False
			_LOGGER.info("Cleared cached data for fresh authentication")
		
		# Force immediate authentication attempt
		try:
			await coordinator._setup_client()
			_LOGGER.info("Manual authentication retry successful")
		except Exception as e:
			_LOGGER.warning(f"Manual authentication retry failed: {e}")
			# Don't raise - let the background retry mechanism handle it
	
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
	
	hass.services.async_register(
		DOMAIN,
		SERVICE_RETRY_AUTH,
		handle_retry_auth,
		schema=SERVICE_RETRY_AUTH_SCHEMA,
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
			hass.services.async_remove(DOMAIN, SERVICE_CLEANUP_DUPLICATES)
			hass.services.async_remove(DOMAIN, SERVICE_RETRY_AUTH)
	
	return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
	"""Reload config entry."""
	await async_unload_entry(hass, entry)
	await async_setup_entry(hass, entry) 