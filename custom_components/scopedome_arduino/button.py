"""Named, bounded dome and shutter controls."""

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_ENCODER_COUNTS_PER_TURN, CONF_ROTATION_STEP,
    CONF_SENSOR_ACTIVE_LEVEL, UNKNOWN_LEVEL,
)
from .cover import async_move_shutter
from .entity import ScopeDomeEntity
from .protocol import MovementBlocked


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities([
        ScopeDomeRotate(entry, coordinator, "CW", "Rotate dome right", "mdi:rotate-right"),
        ScopeDomeRotate(entry, coordinator, "CCW", "Rotate dome left", "mdi:rotate-left"),
        ScopeDomeStopDome(entry, coordinator),
        ScopeDomeMoveShutter(entry, coordinator, "OPEN", "Open shutter", "mdi:window-shutter-open"),
        ScopeDomeMoveShutter(entry, coordinator, "CLOSE", "Close shutter", "mdi:window-shutter"),
        ScopeDomeStopShutter(entry, coordinator),
    ])


class ScopeDomeRotate(ScopeDomeEntity, ButtonEntity):
    """Move by a user-selected, limited number of encoder pulses."""

    def __init__(self, entry, coordinator, direction, name, icon) -> None:
        super().__init__(entry, coordinator, f"rotate_{direction.lower()}")
        self._direction = direction
        self._step = int(entry.options.get(CONF_ROTATION_STEP, 0))
        self._manual_span = entry.options.get(CONF_ENCODER_COUNTS_PER_TURN)
        self._attr_name = name
        self._attr_icon = icon

    @property
    def available(self) -> bool:
        return super().available and self._valid_step

    @property
    def _valid_step(self) -> bool:
        span = self.coordinator.data.rotation_span(self._manual_span)
        if not span:
            return False
        return 1 <= self._step <= min(5000, span // 36)

    async def async_press(self) -> None:
        async with self.coordinator.movement_lock:
            await self.coordinator.async_refresh()
            if not self.coordinator.last_update_success:
                raise HomeAssistantError("Card status is unavailable")
            if not self._valid_step:
                raise HomeAssistantError(
                    "A valid encoder calibration and a rotation step of at most 10 degrees are required"
                )
            try:
                should_send = self.coordinator.data.validate_dome_command(self._direction)
            except MovementBlocked as exc:
                raise HomeAssistantError(str(exc)) from exc
            if not should_send:
                return
            await self.coordinator.client.command(f"moveDome={self._direction}:{self._step}")
            await self.coordinator.async_request_refresh()


class ScopeDomeMoveShutter(ScopeDomeEntity, ButtonEntity):
    """Send a named shutter command using the cover's safety checks."""

    def __init__(self, entry, coordinator, direction, name, icon) -> None:
        super().__init__(entry, coordinator, f"shutter_{direction.lower()}")
        level = entry.options.get(CONF_SENSOR_ACTIVE_LEVEL, UNKNOWN_LEVEL)
        self._active_level = None if level == UNKNOWN_LEVEL else int(level)
        self._direction = direction
        self._attr_name = name
        self._attr_icon = icon

    @property
    def available(self) -> bool:
        return super().available and self._active_level is not None

    async def async_press(self) -> None:
        await async_move_shutter(self.coordinator, self._direction, self._active_level)


class ScopeDomeStopShutter(ScopeDomeEntity, ButtonEntity):
    """Stop shutter movement."""

    _attr_name = "Stop shutter"
    _attr_icon = "mdi:stop"

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "stop_shutter")

    async def async_press(self) -> None:
        await self.coordinator.client.command("stopShutter")
        await self.coordinator.async_request_refresh()


class ScopeDomeStopDome(ScopeDomeEntity, ButtonEntity):
    """Stop dome rotation without changing card configuration."""

    _attr_name = "Stop dome rotation"
    _attr_icon = "mdi:stop"

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "stop_dome")

    async def async_press(self) -> None:
        await self.coordinator.client.command("stopDome")
        await self.coordinator.async_request_refresh()
