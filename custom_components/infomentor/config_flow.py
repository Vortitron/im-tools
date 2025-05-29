"""Config flow for InfoMentor integration."""

import logging
from typing import Any, Dict, Optional

import voluptuous as vol
import aiohttp

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .infomentor import InfoMentorClient
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
		
	async def _test_credentials(self, username: str, password: str) -> None:
		"""Test if the credentials are valid."""
		session = async_get_clientsession(self.hass)
		
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
		"""Manage the options."""
		if user_input is not None:
			return self.async_create_entry(title="", data=user_input)
			
		return self.async_show_form(
			step_id="init",
			data_schema=vol.Schema({
				# Add any options here in the future
				# For example: update interval, which pupils to monitor, etc.
			}),
		) 