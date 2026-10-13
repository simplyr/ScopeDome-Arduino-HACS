"""Reported input bits and link signals without assuming contact polarity."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import ScopeDomeEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities([
        ScopeDomeBinary(entry, coordinator, "slave_online", "Shutter card connected",
                         lambda s: s.slave_online, BinarySensorDeviceClass.CONNECTIVITY),
        ScopeDomeBinary(entry, coordinator, "master_emergency", "Dome emergency",
                         lambda s: s.master.emergency != 0, BinarySensorDeviceClass.PROBLEM),
        ScopeDomeBinary(entry, coordinator, "slave_emergency", "Shutter emergency",
                         lambda s: s.slave.emergency != 0 if s.slave_online else None,
                         BinarySensorDeviceClass.PROBLEM),
        ScopeDomeBinary(entry, coordinator, "home_signal", "Dome home input 1",
                         lambda s: bool(s.master.digital[2]), None),
        ScopeDomeBinary(entry, coordinator, "open_signal", "Shutter open input 1",
                         lambda s: bool(s.slave.digital[3]) if s.slave_online else None, None),
        ScopeDomeBinary(entry, coordinator, "close_signal", "Shutter close input 1",
                         lambda s: bool(s.slave.digital[4]) if s.slave_online else None, None),
    ])


class ScopeDomeBinary(ScopeDomeEntity, BinarySensorEntity):
    """A bit from the SDK status map."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry, coordinator, key, name, getter, device_class) -> None:
        super().__init__(entry, coordinator, key)
        self._attr_name = name
        self._attr_device_class = device_class
        self._getter = getter

    @property
    def is_on(self):
        return self._getter(self.coordinator.data)
