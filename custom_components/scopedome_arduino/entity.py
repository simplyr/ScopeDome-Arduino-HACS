"""Shared entity details."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENCODER_COUNTS_PER_TURN,
    CONF_ENCODER_DIRECTION,
    CONF_HOME_AZIMUTH,
    CONF_HOME_ENCODER_COUNT,
    DOMAIN,
    UNKNOWN_LEVEL,
)


def calibrated_azimuth(status, options) -> float | None:
    """Return no angle until all installation-specific values are supplied."""
    return status.azimuth(
        options.get(CONF_ENCODER_COUNTS_PER_TURN),
        options.get(CONF_HOME_ENCODER_COUNT),
        options.get(CONF_HOME_AZIMUTH),
        options.get(CONF_ENCODER_DIRECTION, UNKNOWN_LEVEL),
    )


class ScopeDomeEntity(CoordinatorEntity):
    """One entity attached to the physical Master card."""

    _attr_has_entity_name = True

    def __init__(self, entry, coordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.unique_id)},
            "name": "ScopeDome Arduino Card",
            "manufacturer": "ScopeDome",
            "model": "Arduino Card 1.3 Master/Slave",
        }
