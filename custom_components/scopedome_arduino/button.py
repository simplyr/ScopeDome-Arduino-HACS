"""Documented stop commands."""

from homeassistant.components.button import ButtonEntity

from .entity import ScopeDomeEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ScopeDomeStopDome(entry, entry.runtime_data)])


class ScopeDomeStopDome(ScopeDomeEntity, ButtonEntity):
    """Stop dome rotation without changing card configuration."""

    _attr_name = "Stop dome rotation"
    _attr_icon = "mdi:stop"

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "stop_dome")

    async def async_press(self) -> None:
        await self.coordinator.client.command("stopDome")
        await self.coordinator.async_request_refresh()
