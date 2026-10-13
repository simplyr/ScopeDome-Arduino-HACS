"""Shutter control, gated by verified contact polarity and live status."""

from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_SENSOR_ACTIVE_LEVEL, UNKNOWN_LEVEL
from .entity import ScopeDomeEntity
from .protocol import MovementBlocked


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ScopeDomeShutter(entry, entry.runtime_data)])


async def async_move_shutter(coordinator, direction: str, active_level: int | None) -> None:
    """Refresh and check safety before issuing a shutter command."""
    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        raise HomeAssistantError("Card status is unavailable")
    try:
        should_send = coordinator.data.validate_shutter_command(direction, active_level)
    except MovementBlocked as exc:
        raise HomeAssistantError(str(exc)) from exc
    if not should_send:
        return
    await coordinator.client.command(f"moveShutter={direction}")
    await coordinator.async_request_refresh()


class ScopeDomeShutter(ScopeDomeEntity, CoverEntity):
    """The paired Slave card's shutter."""

    _attr_name = "Shutter"
    _attr_icon = "mdi:window-shutter"

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "shutter")
        level = entry.options.get(CONF_SENSOR_ACTIVE_LEVEL, UNKNOWN_LEVEL)
        self._active_level = None if level == UNKNOWN_LEVEL else int(level)
        self._attr_supported_features = CoverEntityFeature.STOP
        if self._active_level is not None:
            self._attr_supported_features |= CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    @property
    def is_closed(self):
        state = self.coordinator.data.shutter_state(self._active_level)
        if state == "closed":
            return True
        if state == "open":
            return False
        return None

    @property
    def is_opening(self):
        return self.coordinator.data.shutter_motion == "opening"

    @property
    def is_closing(self):
        return self.coordinator.data.shutter_motion == "closing"

    @property
    def extra_state_attributes(self):
        return {
            "contact_state": self.coordinator.data.shutter_state(self._active_level),
            "motor_state": self.coordinator.data.shutter_motion,
        }

    async def _move(self, direction: str) -> None:
        await async_move_shutter(self.coordinator, direction, self._active_level)

    async def async_open_cover(self, **kwargs):
        await self._move("OPEN")

    async def async_close_cover(self, **kwargs):
        await self._move("CLOSE")

    async def async_stop_cover(self, **kwargs):
        await self.coordinator.client.command("stopShutter")
        await self.coordinator.async_request_refresh()
