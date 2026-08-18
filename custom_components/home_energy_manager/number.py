"""Number platform for Home Energy Manager."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN

POWER_LIMIT_SETTINGS = {
    "inputLimit": ("Input limit", "mdi:battery-arrow-down"),
    "outputLimit": ("Output limit", "mdi:battery-arrow-up"),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up physical SolarFlow power-limit controls."""
    manager = entry.runtime_data.mqtt_manager
    known_entities: set[tuple[str, str]] = set()

    @callback
    def async_add_missing_entities() -> None:
        """Create controls when supported MQTT values are discovered."""
        new_entities: list[SolarFlowPowerLimitNumber] = []

        for device_id, values in manager.number_values.items():
            for setting in POWER_LIMIT_SETTINGS:
                key = (device_id, setting)

                if key in known_entities or setting not in values:
                    continue

                known_entities.add(key)
                new_entities.append(
                    SolarFlowPowerLimitNumber(
                        entry,
                        device_id,
                        setting,
                    )
                )

        if new_entities:
            async_add_entities(new_entities)

    remove_listener = manager.async_add_listener(
        async_add_missing_entities
    )
    entry.async_on_unload(remove_listener)

    async_add_missing_entities()


class SolarFlowPowerLimitNumber(NumberEntity):
    """Control one power limit of one physical SolarFlow."""

    _attr_has_entity_name = True
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_native_min_value = 0.0
    _attr_native_max_value = 2400.0
    _attr_native_step = 1.0
    _attr_mode = "slider"

    def __init__(
        self,
        entry: ConfigEntry,
        device_id: str,
        setting: str,
    ) -> None:
        """Initialize a SolarFlow power-limit number."""
        self._entry = entry
        self._device_id = device_id
        self._setting = setting

        name, icon = POWER_LIMIT_SETTINGS[setting]
        short_id = device_id[-6:]

        self._attr_unique_id = (
            f"{entry.entry_id}_{device_id}_{setting}"
        )
        self._attr_name = f"{name} {short_id}"
        self._attr_icon = icon

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
    def native_value(self) -> float | None:
        """Return the current value from direct MQTT feedback."""
        value = self.mqtt_manager.get_number_value(
            self._device_id,
            self._setting,
        )

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the physical SolarFlow power limit."""
        value = max(
            self.native_min_value,
            min(self.native_max_value, value),
        )

        await self.mqtt_manager.async_set_number_value(
            self._device_id,
            self._setting,
            value,
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
