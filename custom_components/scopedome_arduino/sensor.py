"""Dome counter and interpreted shutter contact state."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import CONF_SENSOR_ACTIVE_LEVEL, UNKNOWN_LEVEL
from .entity import ScopeDomeEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([
        ScopeDomeEncoder(entry, entry.runtime_data),
        ScopeDomeMotion(entry, entry.runtime_data),
        ScopeDomeContactState(entry, entry.runtime_data),
    ])


class ScopeDomeEncoder(ScopeDomeEntity, SensorEntity):
    """Raw motor encoder count, not an azimuth angle."""

    _attr_name = "Dome encoder count"
    _attr_icon = "mdi:counter"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "encoder")

    @property
    def native_value(self):
        return self.coordinator.data.master.encoder


class ScopeDomeContactState(ScopeDomeEntity, SensorEntity):
    """Contact-derived shutter state; unknown until polarity is configured."""

    _attr_name = "Shutter contact state"
    _attr_icon = "mdi:window-shutter"

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "contact_state")
        level = entry.options.get(CONF_SENSOR_ACTIVE_LEVEL, UNKNOWN_LEVEL)
        self._active_level = None if level == UNKNOWN_LEVEL else int(level)

    @property
    def native_value(self):
        return self.coordinator.data.shutter_state(self._active_level)


class ScopeDomeMotion(ScopeDomeEntity, SensorEntity):
    """Dome rotation inferred from the two motor relays."""

    _attr_name = "Dome motion"
    _attr_icon = "mdi:rotate-3d-variant"

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "dome_motion")

    @property
    def native_value(self):
        return self.coordinator.data.dome_motion
