"""UI setup for a local ScopeDome Arduino Master card."""

import ipaddress

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import CardAuthError, CardConnectionError, ScopeDomeClient
from .const import CONF_PASSWORD, CONF_PORT, CONF_SENSOR_ACTIVE_LEVEL, DOMAIN, UNKNOWN_LEVEL
from .protocol import ProtocolError


def _ipv4(value: str) -> str:
    """Use a literal IPv4 address; avoid URL or query injection."""
    try:
        return str(ipaddress.IPv4Address(value.strip()))
    except ipaddress.AddressValueError as exc:
        raise vol.Invalid("Enter the card's IPv4 address") from exc


CONNECTION_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): _ipv4,
    vol.Required(CONF_PORT, default=80): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
    vol.Required(CONF_PASSWORD): TextSelector(
        TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
    ),
})


class ScopeDomeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the card using read-only identity and status requests."""

    VERSION = 1

    async def _probe(self, data: dict) -> str:
        client = ScopeDomeClient(
            async_get_clientsession(self.hass), data[CONF_HOST],
            data[CONF_PORT], data[CONF_PASSWORD],
        )
        _, mac = await client.identify()
        await client.status()
        return mac

    async def async_step_user(self, user_input: dict | None = None):
        errors = {}
        if user_input is not None:
            try:
                mac = await self._probe(user_input)
            except CardAuthError:
                errors["base"] = "invalid_auth"
            except CardConnectionError:
                errors["base"] = "cannot_connect"
            except ProtocolError:
                errors["base"] = "unsupported_status"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"ScopeDome {user_input[CONF_HOST]}", data=user_input,
                )
        return self.async_show_form(
            step_id="user", data_schema=CONNECTION_SCHEMA, errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict | None = None):
        errors = {}
        if user_input is not None:
            entry = self._get_reauth_entry()
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            try:
                mac = await self._probe(data)
            except CardAuthError:
                errors["base"] = "invalid_auth"
            except CardConnectionError:
                errors["base"] = "cannot_connect"
            except ProtocolError:
                errors["base"] = "unsupported_status"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(entry, data_updates=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD,
                                       autocomplete="current-password")
                )
            }),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ScopeDomeOptionsFlow()


class ScopeDomeOptionsFlow(config_entries.OptionsFlow):
    """Require a verified physical signal level before enabling movement."""

    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_SENSOR_ACTIVE_LEVEL, UNKNOWN_LEVEL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_SENSOR_ACTIVE_LEVEL, default=current):
                    vol.In([UNKNOWN_LEVEL, "0", "1"]),
            }),
        )
