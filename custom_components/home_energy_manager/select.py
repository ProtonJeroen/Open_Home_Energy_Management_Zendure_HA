"""Select platform for Home Energy Manager."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN

GRID_OFF_MODE_OPTIONS = [
    "OFF",
    "Normal mode",
    "Economic mode",
]

AC_MODE_OPTIONS = ["Input mode", "Output mode"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up physical SolarFlow select controls."""
    manager = entry.runtime_data.mqtt_manager
    known_entities: set[tuple[str, str]] = set()

    @callback
    def async_add_missing_entities() -> None:
        """Create selects when supported controls are discovered."""
        new_entities: list[SelectEntity] = []

        for device_id, values in manager.select_values.items():
            key = (device_id, "gridOffMode")
            if "gridOffMode" in values and key not in known_entities:
                known_entities.add(key)
                new_entities.append(GridOffModeSelect(entry, device_id))

            key = (device_id, "acMode")
            if "acMode" in values and key not in known_entities:
                known_entities.add(key)
                new_entities.append(AcModeSelect(entry, device_id))

        if new_entities:
            async_add_entities(new_entities)

    remove_listener = manager.async_add_listener(async_add_missing_entities)
    entry.async_on_unload(remove_listener)
    async_add_missing_entities()


class GridOffModeSelect(SelectEntity):
    """Control the off-grid mode of one physical SolarFlow."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:power-socket-eu"
    _attr_options = GRID_OFF_MODE_OPTIONS

    def __init__(
        self,
        entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize the off-grid mode select."""
        self._entry = entry
        self._device_id = device_id

        short_id = device_id[-6:]
        self._attr_unique_id = (
            f"{entry.entry_id}_{device_id}_grid_off_mode"
        )
        self._attr_name = f"Off-gridmodus {short_id}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=f"SolarFlow {short_id}",
            manufacturer="Zendure",
            model="SolarFlow 2400 Pro",
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def mqtt_manager(self):
        """Return the shared Zendure MQTT manager."""
        return self._entry.runtime_data.mqtt_manager

    @property
    def current_option(self) -> str | None:
        """Return the current mode from MQTT feedback."""
        value = self.mqtt_manager.get_select_value(
            self._device_id,
            "gridOffMode",
        )

        if value is None:
            return None

        text = str(value).strip()
        return text if text in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Set the physical SolarFlow off-grid mode."""
        if option not in self.options:
            raise ValueError(
                f"Unsupported gridOffMode option: {option}"
            )

        await self.mqtt_manager.async_set_select_value(
            self._device_id,
            "gridOffMode",
            option,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT cache updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.mqtt_manager.async_add_listener(
                self._async_mqtt_updated
            )
        )

    @callback
    def _async_mqtt_updated(self) -> None:
        """Write MQTT feedback to Home Assistant."""
        self.async_write_ha_state()


class AcModeSelect(SelectEntity):
    """Control AC input/output mode of one physical SolarFlow."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:battery-sync"
    _attr_options = AC_MODE_OPTIONS

    def __init__(self, entry: ConfigEntry, device_id: str) -> None:
        self._entry = entry
        self._device_id = device_id
        short_id = device_id[-6:]
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_ac_mode"
        self._attr_name = f"AC-modus {short_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=f"SolarFlow {short_id}",
            manufacturer="Zendure",
            model="SolarFlow 2400 Pro",
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def mqtt_manager(self):
        return self._entry.runtime_data.mqtt_manager

    @property
    def current_option(self) -> str | None:
        value = self.mqtt_manager.get_select_value(self._device_id, "acMode")
        if value is None:
            return None
        text = str(value).strip()
        return text if text in self.options else None

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Unsupported acMode option: {option}")
        await self.mqtt_manager.async_set_select_value(
            self._device_id, "acMode", option
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.mqtt_manager.async_add_listener(self._async_mqtt_updated)
        )

    @callback
    def _async_mqtt_updated(self) -> None:
        self.async_write_ha_state()
