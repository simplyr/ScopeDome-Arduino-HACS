"""Dome rotation, navigation, and stop controls."""

import asyncio
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import CONF_ENCODER_COUNTS_PER_TURN, CONF_PARK_AZIMUTH, DOMAIN
from .entity import ScopeDomeEntity, calibrated_azimuth
from .protocol import MovementBlocked, azimuth_rotation, rotation_pulses

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    # Remove the retired duplicate buttons, including entries with renamed IDs.
    registry = er.async_get(hass)
    for key in ("shutter_open", "shutter_close", "stop_shutter"):
        entity_id = registry.async_get_entity_id("button", DOMAIN, f"{entry.unique_id}_{key}")
        registered = registry.async_get(entity_id) if entity_id else None
        if registered is not None and registered.config_entry_id == entry.entry_id:
            registry.async_remove(entity_id)
    coordinator = entry.runtime_data
    async_add_entities([
        ScopeDomeRotate(entry, coordinator, "CW", "Rotate dome right", "mdi:rotate-right"),
        ScopeDomeRotate(entry, coordinator, "CCW", "Rotate dome left", "mdi:rotate-left"),
        ScopeDomeStopDome(entry, coordinator),
        ScopeDomeNavigate(entry, coordinator, "find_home", "Find home", "mdi:home-search"),
        ScopeDomeNavigate(entry, coordinator, "go_to_park", "Go to park", "mdi:parking"),
        ScopeDomeNavigate(entry, coordinator, "go_to_azimuth", "Go to azimuth", "mdi:compass"),
    ])


class ScopeDomeRotate(ScopeDomeEntity, ButtonEntity):
    """Move by the angle selected on the device's number control."""

    def __init__(self, entry, coordinator, direction, name, icon, *, key=None) -> None:
        super().__init__(entry, coordinator, key or f"rotate_{direction.lower()}")
        self._direction = direction
        self._manual_span = entry.options.get(CONF_ENCODER_COUNTS_PER_TURN)
        self._attr_name = name
        self._attr_icon = icon

    @property
    def available(self) -> bool:
        return super().available and self._ready

    @property
    def _ready(self) -> bool:
        span = self.coordinator.data.rotation_span(self._manual_span)
        return rotation_pulses(self.coordinator.rotation_angle, span) is not None

    @property
    def _selected_value(self):
        return self.coordinator.rotation_angle

    async def async_press(self) -> None:
        generation = self.coordinator.dome_stop_generation
        angle = self._selected_value
        async with self.coordinator.movement_lock:
            if generation != self.coordinator.dome_stop_generation:
                return
            task = asyncio.current_task()
            self.coordinator.dome_rotation_task = task
            try:
                await self._rotate(angle, generation)
            except asyncio.CancelledError:
                if generation == self.coordinator.dome_stop_generation:
                    raise
            except MovementBlocked as exc:
                raise HomeAssistantError(str(exc)) from exc
            finally:
                if self.coordinator.dome_rotation_task is task:
                    self.coordinator.dome_rotation_task = None

    async def _refresh(self):
        await self.coordinator.async_refresh()
        if not self.coordinator.last_update_success:
            raise HomeAssistantError("Card status is unavailable")
        self.coordinator.data.validate_dome_command(self._direction, allow_stop=True)

    async def _rotate(self, angle, generation):
        await self._refresh()
        span = self.coordinator.data.rotation_span(self._manual_span)
        if rotation_pulses(angle, span) is None:
            raise HomeAssistantError("Choose a valid rotation angle and encoder calibration")
        await self._stop_if_moving()
        if generation != self.coordinator.dome_stop_generation:
            return
        span = self.coordinator.data.rotation_span(self._manual_span)
        pulses = rotation_pulses(angle, span)
        if pulses is None:
            raise HomeAssistantError("Encoder calibration is unavailable")
        # Recheck all card interlocks after confirming a stop.
        self.coordinator.data.validate_dome_command(self._direction)
        _LOGGER.debug(
            "Rotation request: angle_deg=%s span=%s span_source=%s raw_start=%s command=moveDome=%s:%s",
            angle, span,
            "card" if self.coordinator.data.calibrated_rotation else "manual_fallback",
            self.coordinator.data.master.encoder, self._direction, pulses,
        )
        await self.coordinator.client.command(f"moveDome={self._direction}:{pulses}")
        await self.coordinator.async_request_refresh()

    async def _stop_if_moving(self):
        """Share stop confirmation between relative moves and navigation."""
        if self.coordinator.data.dome_motion != "stopped":
            await self.coordinator.client.command("stopDome")
            try:
                async with asyncio.timeout(5):
                    while True:
                        await self._refresh()
                        if self.coordinator.data.dome_motion == "stopped":
                            break
                        await asyncio.sleep(0.25)
            except TimeoutError as exc:
                raise HomeAssistantError(
                    "Dome did not report stopped; new rotation was not sent"
                ) from exc


class ScopeDomeNavigate(ScopeDomeRotate):
    """Find Home with the card, or convert a configured azimuth to a relative move."""

    def __init__(self, entry, coordinator, operation, name, icon) -> None:
        super().__init__(entry, coordinator, "CW", name, icon, key=operation)
        self._operation = operation
        self._options = entry.options

    @property
    def _selected_value(self):
        if self._operation == "go_to_park":
            return self._options.get(CONF_PARK_AZIMUTH)
        if self._operation == "go_to_azimuth":
            return self.coordinator.target_azimuth
        return None

    def _plan(self, target):
        if self._operation == "go_to_park" and target is None:
            raise MovementBlocked("Configure Dome park azimuth before Go to park")
        data = self.coordinator.data
        return azimuth_rotation(calibrated_azimuth(data, self._options), target,
                                data.rotation_span(self._manual_span))

    @property
    def _ready(self) -> bool:
        if self._operation == "find_home":
            return True
        try:
            self._plan(self._selected_value)
        except MovementBlocked:
            return False
        return True

    async def _rotate(self, target, generation):
        await self._refresh()
        if self._operation != "find_home":
            self._plan(target)
        await self._stop_if_moving()
        if generation != self.coordinator.dome_stop_generation:
            return
        if self._operation == "find_home":
            self.coordinator.data.validate_dome_command("CW")
            _LOGGER.debug("Navigation request: raw_start=%s command=findHome",
                          self.coordinator.data.master.encoder)
            await self.coordinator.client.command("findHome")
        else:
            plan = self._plan(target)
            if plan is None:
                return
            direction, pulses = plan
            self.coordinator.data.validate_dome_command(direction)
            _LOGGER.debug(
                "Navigation request: operation=%s target_deg=%s current_deg=%s span=%s raw_start=%s command=moveDome=%s:%s",
                self._operation, target,
                calibrated_azimuth(self.coordinator.data, self._options),
                self.coordinator.data.rotation_span(self._manual_span),
                self.coordinator.data.master.encoder, direction, pulses,
            )
            await self.coordinator.client.command(f"moveDome={direction}:{pulses}")
        await self.coordinator.async_request_refresh()


class ScopeDomeStopDome(ScopeDomeEntity, ButtonEntity):
    """Stop dome rotation without changing card configuration."""

    _attr_name = "Stop dome rotation"
    _attr_icon = "mdi:stop"

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "stop_dome")

    async def async_press(self) -> None:
        self.coordinator.dome_stop_generation += 1
        if (task := self.coordinator.dome_rotation_task) is not None:
            task.cancel()
        await self.coordinator.client.command("stopDome")
        await self.coordinator.async_request_refresh()
