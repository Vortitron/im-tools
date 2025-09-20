"""Config flow for InfoMentor integration."""

import logging
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .infomentor.exceptions import InfoMentorAuthError, InfoMentorConnectionError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
	{
		vol.Required(CONF_USERNAME): str,
		vol.Required(CONF_PASSWORD): str,
	}
)


class InfoMentorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
	"""Handle a config flow for InfoMentor."""
	
	VERSION = 1
	
	async def async_step_user(
		self, user_input: Optional[Dict[str, Any]] = None
	) -> FlowResult:
		"""Handle the initial step."""
		errors: Dict[str, str] = {}
		
		if user_input is not None:
			# Validate the user input
			try:
				await self._test_credentials(
					user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
				)
			except InfoMentorAuthError:
				errors["base"] = "invalid_auth"
			except InfoMentorConnectionError:
				errors["base"] = "cannot_connect"
			except Exception:  # pylint: disable=broad-except
				_LOGGER.exception("Unexpected exception")
				errors["base"] = "unknown"
			else:
				# Create the entry
				await self.async_set_unique_id(user_input[CONF_USERNAME])
				self._abort_if_unique_id_configured()
				
				return self.async_create_entry(
					title=f"InfoMentor ({user_input[CONF_USERNAME]})",
					data=user_input,
				)
		
		return self.async_show_form(
			step_id="user",
			data_schema=STEP_USER_DATA_SCHEMA,
			errors=errors,
		)
	
	async def async_step_reauth(
		self, user_input: Optional[Dict[str, Any]] = None
	) -> FlowResult:
		"""Handle re-authentication."""
		errors: Dict[str, str] = {}
		
		if user_input is not None:
			try:
				# Test the new credentials
				await self._test_credentials(
					user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
				)
			except InfoMentorAuthError:
				errors["base"] = "invalid_auth"
			except InfoMentorConnectionError:
				errors["base"] = "cannot_connect"
			except Exception:  # pylint: disable=broad-except
				_LOGGER.exception("Unexpected exception during reauth")
				errors["base"] = "unknown"
			else:
				# Update the existing entry with new credentials
				existing_entry = await self.async_set_unique_id(user_input[CONF_USERNAME])
				if existing_entry:
					self.hass.config_entries.async_update_entry(
						existing_entry, data=user_input
					)
					await self.hass.config_entries.async_reload(existing_entry.entry_id)
					return self.async_abort(reason="reauth_successful")
				else:
					# If no existing entry found, create a new one
					return self.async_create_entry(
						title=f"InfoMentor ({user_input[CONF_USERNAME]})",
						data=user_input,
					)
		
		# Show the reauth form with current username pre-filled if available
		current_username = self.context.get("source_entry_id")
		if current_username:
			# Try to get the existing username from the entry
			for entry in self.hass.config_entries.async_entries(DOMAIN):
				if entry.entry_id == current_username:
					current_username = entry.data.get(CONF_USERNAME, "")
					break
		
		schema = vol.Schema({
			vol.Required(CONF_USERNAME, default=current_username or ""): str,
			vol.Required(CONF_PASSWORD): str,
		})
		
		return self.async_show_form(
			step_id="reauth",
			data_schema=schema,
			errors=errors,
			description_placeholders={"username": current_username or ""},
		)
		
	async def _test_credentials(self, username: str, password: str) -> None:
		"""Test if the credentials are valid."""
		session = async_get_clientsession(self.hass)
		# Lazy import to avoid heavy imports at module load time
		from .infomentor.client import InfoMentorClient
		async with InfoMentorClient(session) as client:
			await client.login(username, password)
			
		_LOGGER.info("Successfully validated InfoMentor credentials")


class InfoMentorOptionsFlow(config_entries.OptionsFlow):
	"""Handle InfoMentor options."""
	
	def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
		"""Initialise options flow."""
		self.config_entry = config_entry
		
	async def async_step_init(
		self, user_input: Optional[Dict[str, Any]] = None
	) -> FlowResult:
		"""Manage the options, allowing credentials update with validation."""
		errors: Dict[str, str] = {}
		current_username = self.config_entry.data.get(CONF_USERNAME, "")
		
		if user_input is not None:
			username = user_input.get(CONF_USERNAME, current_username)
			password = user_input.get(CONF_PASSWORD)
			
			# Require a password value
			if not password:
				errors["base"] = "invalid_auth"
			else:
				# Test the new credentials
				try:
					session = async_get_clientsession(self.hass)
					async with InfoMentorClient(session) as client:
						await client.login(username, password)
				except InfoMentorAuthError:
					errors["base"] = "invalid_auth"
				except InfoMentorConnectionError:
					errors["base"] = "cannot_connect"
				except Exception:
					_LOGGER.exception("Unexpected exception during credentials test in options")
					errors["base"] = "unknown"
				else:
					# Update entry data with new credentials and reload entry
					new_data = dict(self.config_entry.data)
					new_data[CONF_USERNAME] = username
					new_data[CONF_PASSWORD] = password
					self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
					await self.hass.config_entries.async_reload(self.config_entry.entry_id)
					return self.async_create_entry(title="", data={})
		
		schema = vol.Schema({
			vol.Required(CONF_USERNAME, default=current_username): str,
			vol.Required(CONF_PASSWORD): str,
		})
		
		return self.async_show_form(
			step_id="init",
			data_schema=schema,
			errors=errors,
		)


async def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
	"""Return the options flow for this handler."""
	return InfoMentorOptionsFlow(config_entry)