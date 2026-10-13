"""Safety flags and raw inputs, with interpreted Home only when configured."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import CONF_HOME_ACTIVE_LEVEL, CONF_PARK_AZIMUTH, UNKNOWN_LEVEL
from .entity import ScopeDomeEntity, calibrated_azimuth
from .protocol import emergency_reason


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    home_level = entry.options.get(CONF_HOME_ACTIVE_LEVEL, UNKNOWN_LEVEL)
    home_level = None if home_level == UNKNOWN_LEVEL else int(home_level)
    async_add_entities([
        ScopeDomeBinary(entry, coordinator, "slave_online", "Shutter card connected",
                         lambda s: s.slave_online, BinarySensorDeviceClass.CONNECTIVITY),
        ScopeDomeBinary(entry, coordinator, "master_emergency", "Dome safety alarm",
                         lambda s: s.master.emergency != 0, BinarySensorDeviceClass.PROBLEM,
                         alarm_source="master"),
        ScopeDomeBinary(entry, coordinator, "slave_emergency", "Shutter safety alarm",
                         lambda s: s.slave.emergency != 0 if s.slave_online else None,
                         BinarySensorDeviceClass.PROBLEM, alarm_source="slave"),
        ScopeDomeBinary(entry, coordinator, "at_home", "Dome at home",
                         lambda s: s.at_home(home_level), None, category=None),
        ScopeDomeBinary(entry, coordinator, "at_park", "Dome at park",
                         lambda s: s.at_park(calibrated_azimuth(s, entry.options),
                                             entry.options.get(CONF_PARK_AZIMUTH)),
                         None, category=None),
        ScopeDomeBinary(entry, coordinator, "home_signal", "Dome home switch input",
                         lambda s: bool(s.master.digital[2]), None),
        ScopeDomeBinary(entry, coordinator, "open_signal", "Shutter open limit input",
                         lambda s: bool(s.slave.digital[3]) if s.slave_online else None, None),
        ScopeDomeBinary(entry, coordinator, "close_signal", "Shutter closed limit input",
                         lambda s: bool(s.slave.digital[4]) if s.slave_online else None, None),
        ScopeDomeBinary(entry, coordinator, "telescope_park_signal", "Telescope park switch input",
                         lambda s: bool(s.master.digital[7]), None),
        ScopeDomeBinary(entry, coordinator, "dome_motor_heater", "Dome motor heater",
                         lambda s: s.master.heater_on(3), None, category=None),
        ScopeDomeBinary(entry, coordinator, "shutter_motor_heater", "Shutter motor heater",
                         lambda s: s.slave.heater_on(3) if s.slave_online else None,
                         None, category=None),
        ScopeDomeBinary(entry, coordinator, "dome_electronics_heater",
                         "Dome electronics heater", lambda s: s.master.heater_on(2),
                         None, category=None),
        ScopeDomeBinary(entry, coordinator, "shutter_electronics_heater",
                         "Shutter electronics heater",
                         lambda s: s.slave.heater_on(2) if s.slave_online else None,
                         None, category=None),
        ScopeDomeBinary(entry, coordinator, "card_cloudy", "Cloudy (card sensor)",
                         lambda s: s.master.clouds, None, category=None),
        ScopeDomeBinary(entry, coordinator, "dome_rain_input", "Dome rain input",
                         lambda s: bool(s.master.digital[5]), None),
        ScopeDomeBinary(entry, coordinator, "shutter_rain_input", "Shutter rain input",
                         lambda s: bool(s.slave.digital[5]) if s.slave_online else None,
                         None),
        ScopeDomeBinary(entry, coordinator, "dome_cloud_input", "Dome cloud input",
                         lambda s: bool(s.master.digital[6]), None),
        ScopeDomeBinary(entry, coordinator, "shutter_cloud_input", "Shutter cloud input",
                         lambda s: bool(s.slave.digital[6]) if s.slave_online else None,
                         None),
    ])


class ScopeDomeBinary(ScopeDomeEntity, BinarySensorEntity):
    """A bit from the SDK status map."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry, coordinator, key, name, getter, device_class,
                 *, category=EntityCategory.DIAGNOSTIC, alarm_source=None) -> None:
        super().__init__(entry, coordinator, key)
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_entity_category = category
        self._getter = getter
        self._alarm_source = alarm_source

    @property
    def is_on(self):
        return self._getter(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        if self._alarm_source is None:
            return None
        data = self.coordinator.data
        if self._alarm_source == "slave" and not data.slave_online:
            return None
        value = getattr(data, self._alarm_source).emergency
        return {"alarm_code": value, "alarm_type": emergency_reason(value)}
