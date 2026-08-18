"""Number platform for Home Energy Manager."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN

NUMBER_SETTINGS = {
    "inputLimit": {
        "name": "Input limit",
        "icon": "mdi:battery-arrow-down",
        "device_class": NumberDeviceClass.POWER,
        "unit": UnitOfPower.WATT,
        "min": 0.0,
        "max": 2400.0,
        "step": 1.0,
    },
    "outputLimit": {
        "name": "Output limit",
        "icon": "mdi:battery-arrow-up",
        "device_class": NumberDeviceClass.POWER,
        "unit": UnitOfPower.WATT,
        "min": 0.0,
        "max": 2400.0,
        "step": 1.0,
    },
    "minSoc": {
        "name": "Minimum SoC",
        "icon": "mdi:battery-low",
        "device_class": None,
        "unit": PERCENTAGE,
        "min": 5.0,
        "max": 50.0,
        "step": 1.0,
    },
    "socSet": {
        "name": "Doel-SoC",
        "icon": "mdi:battery-check",
        "device_class": None,
        "unit": PERCENTAGE,
        "min": 70.0,
        "max": 100.0,
        "step": 1.0,
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up physical SolarFlow number controls."""
    manager = entry.runtime_data.mqtt_manager
    known_entities: set[tuple[str, str]] = set()

    @callback
    def async_add_missing_entities() -> None:
        """Create controls when supported MQTT values are discovered."""
        new_entities: list[SolarFlowNumber] = []

        for device_id, values in manager.number_values.items():
            for setting in NUMBER_SETTINGS:
                key = (device_id, setting)

                if key in known_entities or setting not in values:
                    continue

                known_entities.add(key)
                new_entities.append(
                    SolarFlowNumber(
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


class SolarFlowNumber(NumberEntity):
    """Control one numeric setting of one physical SolarFlow."""

    _attr_has_entity_name = True
    _attr_mode = "slider"

    def __init__(
        self,
        entry: ConfigEntry,
        device_id: str,
        setting: str,
    ) -> None:
        """Initialize a SolarFlow number control."""
        self._entry = entry
        self._device_id = device_id
        self._setting = setting

        config = NUMBER_SETTINGS[setting]
        short_id = device_id[-6:]

        self._attr_unique_id = f"{entry.entry_id}_{device_id}_{setting}"
        self._attr_name = f"{config['name']} {short_id}"
        self._attr_icon = config["icon"]
        self._attr_device_class = config["device_class"]
        self._attr_native_unit_of_measurement = config["unit"]
        self._attr_native_min_value = config["min"]
        self._attr_native_max_value = config["max"]
        self._attr_native_step = config["step"]

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
        """Set the physical SolarFlow numeric setting."""
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
