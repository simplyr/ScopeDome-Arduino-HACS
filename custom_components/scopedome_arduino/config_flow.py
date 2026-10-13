"""UI setup for a local ScopeDome Arduino Master card."""

import ipaddress

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import CardAuthError, CardConnectionError, ScopeDomeClient
from .const import (
    CONF_CLOUD_INDEX_THRESHOLD,
    CONF_ENCODER_COUNTS_PER_TURN,
    CONF_ENCODER_DIRECTION,
    CONF_HOME_ACTIVE_LEVEL,
    CONF_HOME_AZIMUTH,
    CONF_HOME_ENCODER_COUNT,
    CONF_PARK_AZIMUTH,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_ROTATION_STEP,
    CONF_SENSOR_ACTIVE_LEVEL,
    DOMAIN,
    UNKNOWN_LEVEL,
)
from .protocol import ProtocolError


def _ipv4(value: str) -> str:
    """Use a literal IPv4 address; avoid URL or query injection."""
    try:
        return str(ipaddress.IPv4Address(value.strip()))
    except ipaddress.AddressValueError as exc:
        raise vol.Invalid("Enter the card's IPv4 address") from exc


CONNECTION_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): TextSelector(),
    vol.Required(CONF_PORT, default=80): NumberSelector(
        NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
    ),
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
                host = _ipv4(user_input[CONF_HOST])
            except vol.Invalid:
                errors[CONF_HOST] = "invalid_host"
            else:
                data = {**user_input, CONF_HOST: host, CONF_PORT: int(user_input[CONF_PORT])}
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
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"ScopeDome {host}", data=data,
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
    """Require verified contacts and a bounded step before movement."""

    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            self._basic_options = user_input
            return await self.async_step_azimuth()
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            last_step=False,
            data_schema=vol.Schema({
                vol.Required(CONF_SENSOR_ACTIVE_LEVEL, default=options.get(
                    CONF_SENSOR_ACTIVE_LEVEL, UNKNOWN_LEVEL
                )):
                    vol.In([UNKNOWN_LEVEL, "0", "1"]),
                vol.Required(CONF_HOME_ACTIVE_LEVEL, default=options.get(
                    CONF_HOME_ACTIVE_LEVEL, UNKNOWN_LEVEL
                )):
                    vol.In([UNKNOWN_LEVEL, "0", "1"]),
                vol.Required(CONF_ROTATION_STEP, default=options.get(
                    CONF_ROTATION_STEP, 0
                )): NumberSelector(NumberSelectorConfig(
                    min=0, max=5000, step=1, mode=NumberSelectorMode.BOX
                )),
            }),
        )

    async def async_step_azimuth(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(data={**self._basic_options, **user_input})
        options = self.config_entry.options
        optional_fields = {}
        for key, minimum, maximum, increment in (
            (CONF_ENCODER_COUNTS_PER_TURN, 1, 1000000, 1),
            (CONF_HOME_ENCODER_COUNT, 0, 1000000, 1),
            (CONF_HOME_AZIMUTH, 0, 359.999999, "any"),
            (CONF_PARK_AZIMUTH, 0, 359.999999, "any"),
            (CONF_CLOUD_INDEX_THRESHOLD, -100, 100, "any"),
        ):
            marker = (vol.Optional(key, default=options[key]) if key in options
                      else vol.Optional(key))
            optional_fields[marker] = NumberSelector(NumberSelectorConfig(
                min=minimum, max=maximum, step=increment, mode=NumberSelectorMode.BOX
            ))
        return self.async_show_form(
            step_id="azimuth",
            last_step=True,
            data_schema=vol.Schema({
                **optional_fields,
                vol.Required(CONF_ENCODER_DIRECTION, default=options.get(
                    CONF_ENCODER_DIRECTION, UNKNOWN_LEVEL
                )): vol.In([UNKNOWN_LEVEL, "cw", "ccw"]),
            }),
        )
