"""Service registration and handlers for the InfoMentor integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Iterable

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
	DOMAIN,
	SERVICE_CLEANUP_DUPLICATES,
	SERVICE_DEBUG_AUTH,
	SERVICE_FORCE_REFRESH,
	SERVICE_REFRESH_DATA,
	SERVICE_RETRY_AUTH,
	SERVICE_SWITCH_PUPIL,
)
from .coordinator import InfoMentorDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

CoordinatorAction = Callable[[str, InfoMentorDataUpdateCoordinator, ServiceCall], Awaitable[None]]

_SERVICES_REGISTERED = False
_REGISTERED_SERVICES = (
	SERVICE_REFRESH_DATA,
	SERVICE_SWITCH_PUPIL,
	SERVICE_FORCE_REFRESH,
	SERVICE_DEBUG_AUTH,
	SERVICE_CLEANUP_DUPLICATES,
	SERVICE_RETRY_AUTH,
)


def _build_schema(extra: dict) -> vol.Schema:
	"""Helper to build schemas with shared optional fields."""
	fields: dict = {vol.Optional("config_entry_id"): str}
	fields.update(extra)
	return vol.Schema(fields)


SERVICE_REFRESH_DATA_SCHEMA = _build_schema({
	vol.Optional("pupil_id"): str,
})

SERVICE_SWITCH_PUPIL_SCHEMA = _build_schema({
	vol.Required("pupil_id"): str,
})

SERVICE_FORCE_REFRESH_SCHEMA = _build_schema({
	vol.Optional("clear_cache", default=True): bool,
})

SERVICE_DEBUG_AUTH_SCHEMA = _build_schema({})

SERVICE_CLEANUP_DUPLICATES_SCHEMA = _build_schema({
	vol.Optional("dry_run", default=False): bool,
	vol.Optional("aggressive_cleanup", default=False): bool,
})

SERVICE_RETRY_AUTH_SCHEMA = _build_schema({
	vol.Optional("clear_cache", default=False): bool,
})


async def async_register_services(hass: HomeAssistant) -> None:
	"""Register InfoMentor services once per Home Assistant instance."""
	global _SERVICES_REGISTERED
	
	if _SERVICES_REGISTERED:
		return
	
	async def handle_refresh_data(call: ServiceCall) -> None:
		await _run_for_targets(hass, call, _action_refresh_data)
	
	async def handle_switch_pupil(call: ServiceCall) -> None:
		await _run_for_targets(hass, call, _action_switch_pupil)
	
	async def handle_force_refresh(call: ServiceCall) -> None:
		await _run_for_targets(hass, call, _action_force_refresh)
	
	async def handle_debug_auth(call: ServiceCall) -> None:
		await _run_for_targets(hass, call, _action_debug_auth)
	
	async def handle_cleanup_duplicates(call: ServiceCall) -> None:
		entry_ids = _get_target_entry_ids(hass, call)
		await _cleanup_duplicate_entities(hass, entry_ids, call)
	
	async def handle_retry_auth(call: ServiceCall) -> None:
		await _run_for_targets(hass, call, _action_retry_auth)
	
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
	
	_SERVICES_REGISTERED = True


async def async_unregister_services(hass: HomeAssistant) -> None:
	"""Remove InfoMentor services when the last entry is unloaded."""
	global _SERVICES_REGISTERED
	
	if not _SERVICES_REGISTERED:
		return
	
	for service in _REGISTERED_SERVICES:
		hass.services.async_remove(DOMAIN, service)
	
	_SERVICES_REGISTERED = False


async def _run_for_targets(
	hass: HomeAssistant,
	call: ServiceCall,
	action: CoordinatorAction,
) -> None:
	"""Execute an action for each targeted coordinator."""
	targets = _get_target_coordinators(hass, call)
	if not targets:
		raise HomeAssistantError("No InfoMentor accounts are currently set up.")
	
	results = await asyncio.gather(
		*(action(entry_id, coordinator, call) for entry_id, coordinator in targets),
		return_exceptions=True,
	)
	
	errors = [result for result in results if isinstance(result, Exception)]
	if not errors:
		return
	
	for err in errors:
		_LOGGER.error("Service %s failed: %s", call.service, err)
	
	if len(errors) == len(targets):
		raise HomeAssistantError(f"{call.service} failed for all targets. Check the logs for details.")
	
	raise HomeAssistantError(f"{call.service} partially failed. Check the logs for details.")


def _get_target_entry_ids(hass: HomeAssistant, call: ServiceCall) -> set[str]:
	"""Resolve which config entries should handle a service call."""
	domain_data = hass.data.get(DOMAIN)
	if not domain_data:
		raise HomeAssistantError("InfoMentor is not currently set up.")
	
	coordinators = {
		entry_id: coordinator
		for entry_id, coordinator in domain_data.items()
		if isinstance(coordinator, InfoMentorDataUpdateCoordinator)
	}
	
	if not coordinators:
		raise HomeAssistantError("InfoMentor coordinators are not ready yet.")
	
	entry_ids: set[str] = set()
	config_entry_id = call.data.get("config_entry_id")
	if config_entry_id:
		if config_entry_id not in coordinators:
			raise HomeAssistantError(f"No InfoMentor account found for config_entry_id '{config_entry_id}'.")
		entry_ids.add(config_entry_id)
	
	device_ids = call.data.get("device_id")
	if device_ids:
		device_registry = dr.async_get(hass)
		for device_id in _ensure_iterable(device_ids):
			device = device_registry.async_get(device_id)
			if not device:
				continue
			for entry_id in device.config_entries:
				if entry_id in coordinators:
					entry_ids.add(entry_id)
	
	if not entry_ids:
		entry_ids = set(coordinators.keys())
	
	return entry_ids


def _get_target_coordinators(
	hass: HomeAssistant,
	call: ServiceCall,
) -> list[tuple[str, InfoMentorDataUpdateCoordinator]]:
	"""Return coordinators that should process the service call."""
	entry_ids = _get_target_entry_ids(hass, call)
	domain_data = hass.data.get(DOMAIN, {})
	targets: list[tuple[str, InfoMentorDataUpdateCoordinator]] = []
	for entry_id in entry_ids:
		coordinator = domain_data.get(entry_id)
		if isinstance(coordinator, InfoMentorDataUpdateCoordinator):
			targets.append((entry_id, coordinator))
	return targets


def _ensure_iterable(value: Any) -> Iterable[str]:
	"""Normalise Home Assistant service data into an iterable of strings."""
	if value is None:
		return []
	if isinstance(value, str):
		return [value]
	if isinstance(value, Iterable):
		return [item for item in value if isinstance(item, str)]
	return []


async def _action_refresh_data(
	entry_id: str,
	coordinator: InfoMentorDataUpdateCoordinator,
	call: ServiceCall,
) -> None:
	"""Handle manual refresh requests."""
	if coordinator._should_backoff():
		backoff_time = coordinator._get_backoff_time()
		raise HomeAssistantError(
			f"Account {coordinator.username} is in backoff for {backoff_time:.0f} seconds."
		)
	
	pupil_id = call.data.get("pupil_id")
	if pupil_id:
		await coordinator.async_refresh_pupil_data(pupil_id)
		_LOGGER.info(
			"Manual refresh completed for pupil %s (account=%s, entry=%s)",
			pupil_id,
			coordinator.username,
			entry_id,
		)
	else:
		await coordinator.async_request_refresh()
		_LOGGER.info(
			"Manual refresh completed for account %s (entry=%s)",
			coordinator.username,
			entry_id,
		)


async def _action_switch_pupil(
	entry_id: str,
	coordinator: InfoMentorDataUpdateCoordinator,
	call: ServiceCall,
) -> None:
	"""Switch the active pupil on demand."""
	pupil_id = call.data["pupil_id"]
	if not coordinator.client:
		raise HomeAssistantError("InfoMentor client is not initialised yet; try again once data has been fetched.")
	
	await coordinator.client.switch_pupil(pupil_id)
	_LOGGER.info(
		"Switched InfoMentor pupil to %s (account=%s, entry=%s)",
		pupil_id,
		coordinator.username,
		entry_id,
	)


async def _action_force_refresh(
	entry_id: str,
	coordinator: InfoMentorDataUpdateCoordinator,
	call: ServiceCall,
) -> None:
	"""Force a refresh, optionally clearing cached data first."""
	clear_cache = call.data.get("clear_cache", True)
	await coordinator.force_refresh(clear_cache)
	_LOGGER.info(
		"Force refresh completed for account %s (entry=%s, cleared_cache=%s)",
		coordinator.username,
		entry_id,
		clear_cache,
	)


async def _action_debug_auth(
	entry_id: str,
	coordinator: InfoMentorDataUpdateCoordinator,
	call: ServiceCall,
) -> None:
	"""Run the detailed authentication debug flow."""
	debug_info = await coordinator.debug_authentication()
	_LOGGER.info(
		"Debug authentication finished for account %s (entry=%s): %s",
		coordinator.username,
		entry_id,
		debug_info,
	)


async def _action_retry_auth(
	entry_id: str,
	coordinator: InfoMentorDataUpdateCoordinator,
	call: ServiceCall,
) -> None:
	"""Retry authentication immediately."""
	clear_cache = call.data.get("clear_cache", False)
	
	coordinator._auth_failure_count = 0
	coordinator._last_auth_failure = None
	coordinator._last_auth_check = None
	
	if clear_cache:
		coordinator.data = None
		coordinator._using_cached_data = False
	
	await coordinator._setup_client()
	_LOGGER.info(
		"Manual authentication retry completed for account %s (entry=%s, cleared_cache=%s)",
		coordinator.username,
		entry_id,
		clear_cache,
	)


async def _cleanup_duplicate_entities(
	hass: HomeAssistant,
	entry_ids: set[str],
	call: ServiceCall,
) -> None:
	"""Remove duplicate InfoMentor entities with optional dry-run."""
	entity_registry = er.async_get(hass)
	dry_run = call.data.get("dry_run", False)
	aggressive = call.data.get("aggressive_cleanup", False)
	
	def _is_target_entry(entry_entry_id: str | None) -> bool:
		return not entry_entry_id or entry_entry_id in entry_ids
	
	infomentor_entities = [
		(entity_id, entry)
		for entity_id, entry in entity_registry.entities.items()
		if entry.platform == DOMAIN and _is_target_entry(entry.config_entry_id)
	]
	
	if not infomentor_entities:
		_LOGGER.info("No InfoMentor entities found for cleanup (entry filter=%s)", entry_ids)
		return
	
	if aggressive:
		to_remove = [entity_id for entity_id, _ in infomentor_entities]
		if dry_run:
			_LOGGER.info("DRY RUN: Would remove %d InfoMentor entities: %s", len(to_remove), sorted(to_remove))
			return
		
		for entity_id in to_remove:
			entity_registry.async_remove(entity_id)
		_LOGGER.info("Removed %d InfoMentor entities (aggressive cleanup)", len(to_remove))
		_LOGGER.info("Restart Home Assistant to allow clean entity recreation.")
		return
	
	base_groups: dict[str, list[tuple[str, er.RegistryEntry]]] = {}
	unique_id_groups: dict[str, list[tuple[str, er.RegistryEntry]]] = {}
	for entity_id, reg_entry in infomentor_entities:
		base_id = entity_id
		for n in range(2, 10):
			suffix = f"_{n}"
			if entity_id.endswith(suffix):
				base_id = entity_id[:-len(suffix)]
				break
		base_groups.setdefault(base_id, []).append((entity_id, reg_entry))
		
		if reg_entry.unique_id:
			unique_id_groups.setdefault(reg_entry.unique_id, []).append((entity_id, reg_entry))
	
	to_remove: set[str] = set()
	for base_id, group in base_groups.items():
		if len(group) > 1 and any(eid == base_id for eid, _ in group):
			to_remove.update(eid for eid, _ in group if eid != base_id)
	
	for group in unique_id_groups.values():
		if len(group) > 1:
			group.sort(
				key=lambda item: (
					any(item[0].endswith(f"_{i}") for i in range(2, 10)),
					len(item[0]),
					item[0],
				)
			)
			for entity_id, _ in group[1:]:
				to_remove.add(entity_id)
	
	if not to_remove:
		_LOGGER.info("No duplicate InfoMentor entities detected for cleanup scope %s", entry_ids)
		return
	
	if dry_run:
		_LOGGER.info("DRY RUN: Would remove %d duplicate entities: %s", len(to_remove), sorted(to_remove))
		return
	
	for entity_id in to_remove:
		entity_registry.async_remove(entity_id)
	
	for entity_id, reg_entry in infomentor_entities:
		if entity_id in to_remove:
			continue
		updates = {}
		if reg_entry.disabled_by is not None:
			updates["disabled_by"] = None
		if reg_entry.hidden_by is not None:
			updates["hidden_by"] = None
		if updates:
			entity_registry.async_update_entity(entity_id, **updates)
	
	_LOGGER.info("Removed %d duplicate InfoMentor entities", len(to_remove))
	if len(to_remove) > 0:
		_LOGGER.info("Restart Home Assistant to allow entities to be recreated if required.")

