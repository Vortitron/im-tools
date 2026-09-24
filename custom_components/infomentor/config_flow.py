"""Config flow for InfoMentor integration."""

import logging
from typing import Any, Dict, Mapping, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
	BooleanSelector,
	SelectSelector,
	SelectSelectorConfig,
	SelectSelectorMode,
)

from .infomentor.exceptions import InfoMentorAuthError, InfoMentorConnectionError

from .const import DOMAIN, CONF_NOTIFY_SERVICES, CONF_PERSISTENT_NOTIFICATION

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
	{
		vol.Required(CONF_USERNAME): str,
		vol.Required(CONF_PASSWORD): str,
	}
)


async def _test_credentials(hass: HomeAssistant, username: str, password: str) -> None:
	"""Test if the credentials are valid.

	Uses a throwaway session so a test login can't overwrite the cookies of an
	already running InfoMentor entry.
	"""
	session = async_create_clientsession(hass, auto_cleanup=False)
	try:
		# Lazy import to avoid heavy imports at module load time
		from .infomentor.client import InfoMentorClient
		async with InfoMentorClient(session) as client:
			await client.login(username, password)
	finally:
		session.detach()

	_LOGGER.info("Successfully validated InfoMentor credentials")


async def _validate(hass: HomeAssistant, username: str, password: str) -> Dict[str, str]:
	"""Return a form errors dict (empty when the credentials work)."""
	try:
		await _test_credentials(hass, username, password)
	except InfoMentorAuthError:
		return {"base": "invalid_auth"}
	except InfoMentorConnectionError:
		return {"base": "cannot_connect"}
	except Exception:  # pylint: disable=broad-except
		_LOGGER.exception("Unexpected exception while validating credentials")
		return {"base": "unknown"}
	return {}


class InfoMentorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
	"""Handle a config flow for InfoMentor."""

	VERSION = 1

	@staticmethod
	@callback
	def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
		"""Return the options flow for this handler."""
		return InfoMentorOptionsFlow(config_entry)

	async def async_step_user(
		self, user_input: Optional[Dict[str, Any]] = None
	) -> FlowResult:
		"""Handle the initial step."""
		errors: Dict[str, str] = {}

		if user_input is not None:
			await self.async_set_unique_id(user_input[CONF_USERNAME])
			self._abort_if_unique_id_configured()

			errors = await _validate(self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
			if not errors:
				return self.async_create_entry(
					title=f"InfoMentor ({user_input[CONF_USERNAME]})",
					data=user_input,
				)

		return self.async_show_form(
			step_id="user",
			data_schema=STEP_USER_DATA_SCHEMA,
			errors=errors,
		)

	async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
		"""Start re-authentication when stored credentials stop working."""
		return await self.async_step_reauth_confirm()

	async def async_step_reauth_confirm(
		self, user_input: Optional[Dict[str, Any]] = None
	) -> FlowResult:
		"""Ask for a new password for the existing account."""
		errors: Dict[str, str] = {}
		entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
		if entry is None:
			return self.async_abort(reason="reauth_failed")
		username = entry.data[CONF_USERNAME]

		if user_input is not None:
			errors = await _validate(self.hass, username, user_input[CONF_PASSWORD])
			if not errors:
				self.hass.config_entries.async_update_entry(
					entry, data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
				)
				await self.hass.config_entries.async_reload(entry.entry_id)
				return self.async_abort(reason="reauth_successful")

		return self.async_show_form(
			step_id="reauth_confirm",
			data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
			errors=errors,
			description_placeholders={"username": username},
		)


def _as_service_list(value: Any) -> list[str]:
	"""Notify services as a list; older versions stored a comma-separated string."""
	if not value:
		return []
	if isinstance(value, str):
		value = value.split(",")
	return [str(v).strip() for v in value if str(v).strip()]


class InfoMentorOptionsFlow(config_entries.OptionsFlow):
	"""Handle InfoMentor options."""

	def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
		"""Initialise options flow."""
		# Not assigned to self.config_entry: newer HA sets that itself and rejects assignment
		self._entry = config_entry

	def _available_notify_services(self) -> list[str]:
		"""Legacy notify services (e.g. mobile_app_<phone>) that accept title/message/data."""
		services = self.hass.services.async_services().get("notify", {})
		return [name for name in services if name not in ("send_message", "persistent_notification")]

	async def async_step_init(
		self, user_input: Optional[Dict[str, Any]] = None
	) -> FlowResult:
		"""Manage options: credentials and notification settings."""
		errors: Dict[str, str] = {}
		current_username = self._entry.data.get(CONF_USERNAME, "")
		current_notify = _as_service_list(self._entry.options.get(CONF_NOTIFY_SERVICES))
		current_persistent = bool(self._entry.options.get(CONF_PERSISTENT_NOTIFICATION, False))

		if user_input is not None:
			username = (user_input.get(CONF_USERNAME) or current_username).strip()
			# Blank password keeps the stored one, so notify services can be changed alone
			password = user_input.get(CONF_PASSWORD) or self._entry.data.get(CONF_PASSWORD, "")
			notify_services = _as_service_list(user_input.get(CONF_NOTIFY_SERVICES))
			persistent = bool(user_input.get(CONF_PERSISTENT_NOTIFICATION, False))
			credentials_changed = (
				username != current_username
				or password != self._entry.data.get(CONF_PASSWORD, "")
			)

			if credentials_changed:
				errors = await _validate(self.hass, username, password)

			if not errors:
				if credentials_changed:
					self.hass.config_entries.async_update_entry(
						self._entry,
						data={**self._entry.data, CONF_USERNAME: username, CONF_PASSWORD: password},
					)
					self.hass.async_create_task(
						self.hass.config_entries.async_reload(self._entry.entry_id)
					)
				# Notify services are read live from the options, no reload needed
				return self.async_create_entry(
					title="",
					data={CONF_NOTIFY_SERVICES: notify_services, CONF_PERSISTENT_NOTIFICATION: persistent},
				)

		schema = vol.Schema({
			vol.Required(CONF_USERNAME, default=current_username): str,
			vol.Optional(CONF_PASSWORD): str,
			# suggested_value rather than default, so the field can be cleared
			vol.Optional(CONF_NOTIFY_SERVICES, description={"suggested_value": current_notify}): SelectSelector(
				SelectSelectorConfig(
					options=sorted(set(self._available_notify_services()) | set(current_notify)),
					multiple=True,
					custom_value=True,
					mode=SelectSelectorMode.DROPDOWN,
				)
			),
			vol.Optional(CONF_PERSISTENT_NOTIFICATION, default=current_persistent): BooleanSelector(),
		})

		return self.async_show_form(
			step_id="init",
			data_schema=schema,
			errors=errors,
		)
