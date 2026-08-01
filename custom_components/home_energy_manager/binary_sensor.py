"""Binary sensor platform for Home Energy Manager."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_BALANCE_THRESHOLD
from .entity import HomeEnergyManagerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Home Energy Manager binary sensors."""
    source_entities: set[str] = set()

    async_add_entities(
        [
            AllOnlineBinarySensor(entry, source_entities),
            BalancedBinarySensor(entry, source_entities),
        ]
    )


class BaseBinarySensor(HomeEnergyManagerEntity, BinarySensorEntity):
    """Base binary sensor."""

    def __init__(
        self,
        entry: ConfigEntry,
        source_entities: set[str],
        key: str,
        name: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(entry, source_entities)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name

    @property
    def mqtt_manager(self):
        """Return the shared Zendure MQTT manager."""
        return self._entry.runtime_data.mqtt_manager


class AllOnlineBinarySensor(BaseBinarySensor):
    """Whether all configured batteries are available."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, entry, source_entities) -> None:
        super().__init__(entry, source_entities, "all_online", "Alle accu's online")

    @property
    def is_on(self) -> bool:
        device_count = self.mqtt_manager.get_device_count()

        if device_count == 0:
            return False

        return (
            self.mqtt_manager.count_measurement("electricLevel")
            == device_count
        )


class BalancedBinarySensor(BaseBinarySensor):
    """Whether the batteries are within the configured SoC spread."""

    _attr_icon = "mdi:scale-balance"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(entry, source_entities, "balanced", "Accu's in balans")
        self._threshold = float(entry.data[CONF_BALANCE_THRESHOLD])

    @property
    def is_on(self) -> bool | None:
        device_count = self.mqtt_manager.get_device_count()
        values = self.mqtt_manager.get_numeric_values("electricLevel")

        if device_count == 0 or len(values) != device_count:
            return None

        return (max(values) - min(values)) <= self._threshold

    @property
    def extra_state_attributes(self) -> dict[str, float | int]:
        values = self.mqtt_manager.get_numeric_values("electricLevel")

        return {
            "drempel": self._threshold,
            "soc_verschil": (
                round(max(values) - min(values), 1)
                if len(values) >= 2
                else 0.0
            ),
            "beschikbare_accus": len(values),
            "gedetecteerde_accus": self.mqtt_manager.get_device_count(),
        }
