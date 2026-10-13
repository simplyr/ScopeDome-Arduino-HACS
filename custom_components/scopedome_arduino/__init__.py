"""ScopeDome Arduino Card integration."""

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CardAuthError, CardConnectionError, ScopeDomeClient
from .const import CONF_PASSWORD, CONF_PORT, DOMAIN, SCAN_INTERVAL
from .protocol import DomeStatus, ProtocolError

PLATFORMS = ["binary_sensor", "button", "cover", "number", "sensor"]
_LOGGER = logging.getLogger(__name__)


class ScopeDomeCoordinator(DataUpdateCoordinator[DomeStatus]):
    """Poll one paired Master/Slave dome."""

    def __init__(self, hass: HomeAssistant, client: ScopeDomeClient) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.client = client
        self.movement_lock = asyncio.Lock()
        self.rotation_angle = 0.0
        self.dome_stop_generation = 0
        self.dome_rotation_task = None

    async def _async_update_data(self) -> DomeStatus:
        try:
            return await self.client.status()
        except CardAuthError as exc:
            raise ConfigEntryAuthFailed("ScopeDome password rejected") from exc
        except (CardConnectionError, ProtocolError) as exc:
            raise UpdateFailed(str(exc)) from exc


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = ScopeDomeClient(
        async_get_clientsession(hass), entry.data["host"],
        entry.data[CONF_PORT], entry.data[CONF_PASSWORD],
    )
    coordinator = ScopeDomeCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
