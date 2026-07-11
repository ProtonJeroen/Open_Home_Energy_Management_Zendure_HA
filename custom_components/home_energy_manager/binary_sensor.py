"""Binary sensor platform for Home Energy Manager."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_BALANCE_THRESHOLD,
    CONF_SOC_ENTITIES,
)
from .entity import HomeEnergyManagerEntity
from .sensor import _numeric_states


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Home Energy Manager binary sensors."""
    soc_entities = list(entry.data[CONF_SOC_ENTITIES])
    source_entities = set(soc_entities)

    async_add_entities(
        [
            AllOnlineBinarySensor(entry, source_entities, soc_entities),
            BalancedBinarySensor(entry, source_entities, soc_entities),
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


class AllOnlineBinarySensor(BaseBinarySensor):
    """Whether all configured batteries are available."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, entry, source_entities, soc_entities) -> None:
        super().__init__(entry, source_entities, "all_online", "Alle accu's online")
        self._soc_entities = soc_entities

    @property
    def is_on(self) -> bool:
        return (
            len(_numeric_states(self.hass, self._soc_entities))
            == len(self._soc_entities)
        )


class BalancedBinarySensor(BaseBinarySensor):
    """Whether the batteries are within the configured SoC spread."""

    _attr_icon = "mdi:scale-balance"

    def __init__(self, entry, source_entities, soc_entities) -> None:
        super().__init__(entry, source_entities, "balanced", "Accu's in balans")
        self._soc_entities = soc_entities
        self._threshold = float(entry.data[CONF_BALANCE_THRESHOLD])

    @property
    def is_on(self) -> bool | None:
        values = _numeric_states(self.hass, self._soc_entities)
        if len(values) != len(self._soc_entities):
            return None
        return (max(values) - min(values)) <= self._threshold
