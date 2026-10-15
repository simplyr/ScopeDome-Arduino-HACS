"""Saved dome angles; editing a value does not move the dome."""

from math import isfinite

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_ENCODER_COUNTS_PER_TURN, CONF_ROTATION_STEP
from .entity import ScopeDomeEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    span = coordinator.data.rotation_span(entry.options.get(CONF_ENCODER_COUNTS_PER_TURN))
    old_step = entry.options.get(CONF_ROTATION_STEP, 0)
    if span and 0 <= old_step <= min(5000, span // 36):
        coordinator.rotation_angle = round(old_step * 360 / span, 1)
    async_add_entities([
        ScopeDomeRotationAngle(entry, coordinator),
        ScopeDomeTargetAzimuth(entry, coordinator),
    ])


class ScopeDomeRotationAngle(ScopeDomeEntity, RestoreNumber):
    """Choose degrees before pressing Rotate dome left or right."""

    _attr_name = "Dome rotation angle"
    _attr_icon = "mdi:angle-acute"
    _attr_native_unit_of_measurement = "°"
    _attr_native_min_value = 0
    _attr_native_max_value = 10
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _value_attribute = "rotation_angle"

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, self._value_attribute)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if (restored := await self.async_get_last_number_data()) is not None:
            value = restored.native_value
            if (isinstance(value, (int, float)) and isfinite(value)
                    and 0 <= value <= self._attr_native_max_value):
                setattr(self.coordinator, self._value_attribute, float(value))
        self.coordinator.async_update_listeners()

    @property
    def native_value(self):
        return getattr(self.coordinator, self._value_attribute)

    async def async_set_native_value(self, value: float):
        if not isfinite(value) or not 0 <= value <= self._attr_native_max_value:
            raise HomeAssistantError(
                f"Choose {self._attr_name} from 0 to {self._attr_native_max_value} degrees"
            )
        setattr(self.coordinator, self._value_attribute, float(value))
        self.coordinator.async_update_listeners()
        self.async_write_ha_state()


class ScopeDomeTargetAzimuth(ScopeDomeRotationAngle):
    """An absolute target used only when Go to azimuth is pressed."""

    _attr_name = "Dome target azimuth"
    _attr_icon = "mdi:compass-outline"
    _attr_native_max_value = 360
    _value_attribute = "target_azimuth"
