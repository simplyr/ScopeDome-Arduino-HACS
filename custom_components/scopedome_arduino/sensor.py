"""Dome counter and interpreted shutter contact state."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.helpers.entity import EntityCategory

from .const import (
    CONF_CLOUD_INDEX_THRESHOLD, CONF_HOME_AZIMUTH,
    CONF_SENSOR_ACTIVE_LEVEL, UNKNOWN_LEVEL,
)
from .entity import ScopeDomeEntity, calibrated_azimuth
from .protocol import compass_direction, emergency_reason, humidity, temperature


def station_reading(status, group: str, index: int, normalize=temperature,
                    *, prefer_slave: bool = True):
    """Read a weather probe from its expected card, with the other as fallback."""
    cards = ([status.slave, status.master] if prefer_slave
             else [status.master, status.slave])
    for card in cards:
        if card is status.slave and not status.slave_online:
            continue
        value = normalize(getattr(card, group)[index])
        if value is not None:
            return value
    return None


def observed_cloud_index(status):
    """Sky minus outside temperature, checked on the same card."""
    cards = ([status.slave] if status.slave_online else []) + [status.master]
    for card in cards:
        sky = temperature(card.temperatures[8])
        outside = temperature(card.temperatures[3])
        if sky is not None and outside is not None:
            return round(sky - outside, 1)
    return None


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([
        ScopeDomeEncoder(entry, entry.runtime_data),
        ScopeDomeAzimuth(entry, entry.runtime_data),
        ScopeDomeCompass(entry, entry.runtime_data),
        ScopeDomeHomeAzimuth(entry, entry.runtime_data),
        ScopeDomeMotion(entry, entry.runtime_data),
        ScopeDomeContactState(entry, entry.runtime_data),
        ScopeDomeAlarmReason(entry, entry.runtime_data, "master", "Dome alarm source"),
        ScopeDomeAlarmReason(entry, entry.runtime_data, "slave", "Shutter alarm source"),
        ScopeDomeWeather(entry, entry.runtime_data, "dome_electronics_temperature",
                         "Dome electronics temperature",
                         lambda s: temperature(s.master.temperatures[0]), "temperature"),
        ScopeDomeWeather(entry, entry.runtime_data, "shutter_electronics_temperature",
                         "Shutter electronics temperature",
                         lambda s: temperature(s.slave.temperatures[0]) if s.slave_online else None,
                         "temperature"),
        ScopeDomeWeather(entry, entry.runtime_data, "dome_motor_temperature",
                         "Dome motor temperature",
                         lambda s: temperature(s.master.temperatures[2]), "temperature"),
        ScopeDomeWeather(entry, entry.runtime_data, "shutter_motor_temperature",
                         "Shutter motor temperature",
                         lambda s: temperature(s.slave.temperatures[2]) if s.slave_online else None,
                         "temperature"),
        ScopeDomeWeather(entry, entry.runtime_data, "outside_temperature",
                         "Outside temperature",
                         lambda s: station_reading(s, "temperatures", 3), "temperature"),
        ScopeDomeWeather(entry, entry.runtime_data, "hygrometer_temperature",
                         "Hygrometer temperature",
                         lambda s: station_reading(s, "temperatures", 6,
                                                   prefer_slave=False), "temperature"),
        ScopeDomeWeather(entry, entry.runtime_data, "relative_humidity",
                         "Relative humidity",
                         lambda s: station_reading(s, "instruments", 1, humidity,
                                                   prefer_slave=False), "humidity"),
        ScopeDomeWeather(entry, entry.runtime_data, "pyrometer_ambient",
                         "Pyrometer ambient temperature",
                         lambda s: station_reading(s, "temperatures", 7), "temperature"),
        ScopeDomeWeather(entry, entry.runtime_data, "sky_temperature",
                         "Sky temperature",
                         lambda s: station_reading(s, "temperatures", 8), "temperature"),
        ScopeDomeWeather(entry, entry.runtime_data, "observed_cloud_index",
                         "Observed cloud index", observed_cloud_index, "temperature_difference"),
        ScopeDomeWeather(entry, entry.runtime_data, "cloud_index_threshold",
                         "Cloud index threshold",
                         lambda s: entry.options.get(CONF_CLOUD_INDEX_THRESHOLD),
                         "temperature_difference"),
        ScopeDomeCloudCode(entry, entry.runtime_data, "master", "Dome cloud code"),
        ScopeDomeCloudCode(entry, entry.runtime_data, "slave", "Shutter cloud code"),
    ])


class ScopeDomeWeather(ScopeDomeEntity, SensorEntity):
    """Read a documented environmental field from the paired card status."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry, coordinator, key, name, getter, kind) -> None:
        super().__init__(entry, coordinator, key)
        self._attr_name = name
        self._getter = getter
        if key == "cloud_index_threshold":
            self._attr_state_class = None
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if kind == "humidity":
            self._attr_device_class = SensorDeviceClass.HUMIDITY
            self._attr_native_unit_of_measurement = "%"
        else:
            self._attr_native_unit_of_measurement = "°C"
            if kind == "temperature":
                self._attr_device_class = SensorDeviceClass.TEMPERATURE

    @property
    def native_value(self):
        return self._getter(self.coordinator.data)


class ScopeDomeCloudCode(ScopeDomeEntity, SensorEntity):
    """Preserve the controller's raw cloud-check code for diagnosis."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-alert"

    def __init__(self, entry, coordinator, card, name) -> None:
        super().__init__(entry, coordinator, f"{card}_cloud_code")
        self._card = card
        self._attr_name = name

    @property
    def native_value(self):
        status = self.coordinator.data
        if self._card == "slave" and not status.slave_online:
            return None
        return getattr(status, self._card).cloud_code


class ScopeDomeEncoder(ScopeDomeEntity, SensorEntity):
    """Raw motor encoder count, not an azimuth angle."""

    _attr_name = "Dome raw encoder count"
    _attr_icon = "mdi:counter"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "encoder")

    @property
    def native_value(self):
        return self.coordinator.data.master.encoder


class ScopeDomeAzimuth(ScopeDomeEntity, SensorEntity):
    """Angle derived from installation-specific encoder calibration."""

    _attr_name = "Dome azimuth"
    _attr_icon = "mdi:compass-outline"
    _attr_native_unit_of_measurement = "°"

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "azimuth")
        self._options = entry.options

    @property
    def native_value(self):
        value = calibrated_azimuth(self.coordinator.data, self._options)
        return None if value is None else round(value, 1)


class ScopeDomeCompass(ScopeDomeEntity, SensorEntity):
    """Readable compass direction from a calibrated azimuth."""

    _attr_name = "Dome direction"
    _attr_icon = "mdi:compass"

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "compass_direction")
        self._options = entry.options

    @property
    def native_value(self):
        azimuth = calibrated_azimuth(self.coordinator.data, self._options)
        return None if azimuth is None else compass_direction(azimuth)


class ScopeDomeHomeAzimuth(ScopeDomeEntity, SensorEntity):
    """Display the configured physical Home orientation."""

    _attr_name = "Home azimuth"
    _attr_icon = "mdi:home-map-marker"
    _attr_native_unit_of_measurement = "°"

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "home_azimuth")
        self._options = entry.options

    @property
    def native_value(self):
        return self._options.get(CONF_HOME_AZIMUTH)


class ScopeDomeContactState(ScopeDomeEntity, SensorEntity):
    """Contact-derived shutter state; unknown until polarity is configured."""

    _attr_name = "Shutter position"
    _attr_icon = "mdi:window-shutter"

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "contact_state")
        level = entry.options.get(CONF_SENSOR_ACTIVE_LEVEL, UNKNOWN_LEVEL)
        self._active_level = None if level == UNKNOWN_LEVEL else int(level)

    @property
    def native_value(self):
        data = self.coordinator.data
        state = data.shutter_state(self._active_level)
        if state == "between" and data.shutter_motion in ("opening", "closing"):
            return data.shutter_motion.capitalize()
        return {
            "open": "Open",
            "closed": "Closed",
            "between": "Between end stops",
            "fault": "Conflicting limit switches",
            "unknown": "Unknown",
        }[state]

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        return {
            "open_input": data.slave.digital[3] if data.slave_online else None,
            "closed_input": data.slave.digital[4] if data.slave_online else None,
            "active_input_value": self._active_level,
        }


class ScopeDomeAlarmReason(ScopeDomeEntity, SensorEntity):
    """Show the SDK's alarm class and raw numeric code."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, entry, coordinator, card, name) -> None:
        super().__init__(entry, coordinator, f"{card}_alarm_source")
        self._card = card
        self._attr_name = name

    @property
    def native_value(self):
        data = self.coordinator.data
        if self._card == "slave" and not data.slave_online:
            return None
        return emergency_reason(getattr(data, self._card).emergency)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        if self._card == "slave" and not data.slave_online:
            return None
        return {"alarm_code": getattr(data, self._card).emergency}


class ScopeDomeMotion(ScopeDomeEntity, SensorEntity):
    """Dome rotation inferred from the two motor relays."""

    _attr_name = "Dome motion"
    _attr_icon = "mdi:rotate-3d-variant"

    def __init__(self, entry, coordinator) -> None:
        super().__init__(entry, coordinator, "dome_motion")

    @property
    def native_value(self):
        return self.coordinator.data.dome_motion
