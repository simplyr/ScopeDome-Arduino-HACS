"""Shared entity details."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


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
