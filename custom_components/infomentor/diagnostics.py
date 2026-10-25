"""Home Assistant diagnostics support for the InfoMentor integration.

Adds a "Download Diagnostics" link on the integration's device page in
Settings → Devices & services, which bundles up a JSON file with the
current state of the coordinator, recent diagnostic events, cookie domain
summary and the latest notification buffer.

Credentials, the account name, pupil IDs and cookie values are redacted. This is the user-friendly way
of inspecting what the integration is doing without needing shell access
to the VM running Home Assistant.
"""

from __future__ import annotations

from typing import Any, Dict

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .coordinator import InfoMentorDataUpdateCoordinator


# async_redact_data matches by key name anywhere in the payload. The entry
# title is "InfoMentor (<username>)", so it is redacted alongside the username.
REDACT_KEYS = {
	CONF_PASSWORD,
	CONF_USERNAME,
	"password",
	"token",
	"cookie",
	"cookies",
	"set-cookie",
	"title",
	"pupil_ids",
	"pupils",
	"pupil_im2_id",
}


async def async_get_config_entry_diagnostics(
	hass: HomeAssistant,
	entry: ConfigEntry,
) -> Dict[str, Any]:
	"""Return diagnostics for the given config entry."""
	coordinator: InfoMentorDataUpdateCoordinator | None = (
		hass.data.get(DOMAIN, {}).get(entry.entry_id)
	)

	payload: Dict[str, Any] = {
		"entry": {
			"title": entry.title,
			"entry_id": entry.entry_id,
			"version": entry.version,
			"options": dict(entry.options or {}),
		},
		"coordinator": None,
	}

	if coordinator is not None:
		cookies_by_domain: Dict[str, int] = {}
		if coordinator._session and getattr(coordinator._session, "cookie_jar", None):
			for cookie in coordinator._session.cookie_jar:
				try:
					dom = cookie["domain"] or "?"
				except Exception:
					dom = "?"
				cookies_by_domain[dom] = cookies_by_domain.get(dom, 0) + 1

		last_update = coordinator._last_successful_update
		coord_info: Dict[str, Any] = {
			"pupil_ids": list(coordinator.pupil_ids or []),
			"pupil_count": len(coordinator.pupil_ids or []),
			"authenticated": bool(coordinator.client and coordinator.client.authenticated)
				if coordinator.client else False,
			"last_successful_update": last_update.isoformat() if last_update else None,
			"auth_failure_count": coordinator._auth_failure_count,
			"daily_retry_count": coordinator._daily_retry_count,
			"today_data_available": coordinator._today_data_available,
			"last_notification_check": (
				coordinator._last_notification_check.isoformat()
				if coordinator._last_notification_check else None
			),
			"notifications_in_buffer": len(coordinator.notifications),
			"seen_notification_ids": len(coordinator._seen_notification_ids),
			"cookies_by_domain": cookies_by_domain,
			"cookies_total": sum(cookies_by_domain.values()),
			"diagnostic_events": coordinator.diagnostic_events,
		}

		recent_notifications = []
		for n in coordinator.notifications[:20]:
			recent_notifications.append({
				"id": n.id,
				"title": n.title,
				"type": n.notification_type,
				"state": n.state,
				"date_sent": n.date_sent.isoformat() if n.date_sent else None,
				"app_type": n.app_type,
				"pupil_im2_id": n.pupil_im2_id,
			})
		coord_info["recent_notifications"] = recent_notifications

		# Counts only: whether assignments/calendar work for each pupil.
		# Keyed by position so the pupil IDs are not published.
		extras = {}
		for index, pupil_id in enumerate(coordinator.pupil_ids or [], start=1):
			tasks = coordinator.get_pupil_tasks(pupil_id)
			extras[f"pupil_{index}"] = {
				"tasks_available": tasks is not None,
				"tasks": len(tasks.get("items") or []) if tasks else 0,
				"calendar_events": len(coordinator.get_pupil_calendar(pupil_id)),
			}
		coord_info["pupil_extras"] = extras
		coord_info["lunch_unit"] = coordinator.lunch_unit
		coord_info["lunch_days"] = len(coordinator.lunch_menu)

		payload["coordinator"] = coord_info

	return async_redact_data(payload, REDACT_KEYS)
