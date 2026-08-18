"""Home Energy Manager integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias

from homeassistant.components import mqtt
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS

_LOGGER = logging.getLogger(__name__)

MqttValue: TypeAlias = float | str | None

ZENDURE_SENSOR_TOPIC = "Zendure/sensor"
ZENDURE_NUMBER_TOPIC = "Zendure/number"
ZENDURE_SWITCH_TOPIC = "Zendure/switch"
ZENDURE_SELECT_TOPIC = "Zendure/select"

ZENDURE_MEASUREMENTS = {
    # Main SolarFlow measurements
    "outputPackPower",
    "packInputPower",
    "outputHomePower",
    "gridInputPower",
    "gridOffPower",
    "solarInputPower",
    "solarPower1",
    "solarPower2",
    "solarPower3",
    "solarPower4",
    "electricLevel",
    "packState",
    "hyperTmp",
    "heatState",
    "socStatus",
    "remainOutTime",

    # Battery-pack measurements
    "maxTemp",
    "minVol",
    "maxVol",
    "totalVol",
    "batcur",
    "softVersion",
}

TEXT_MEASUREMENTS = {
    "packState",
    "heatState",
    "socStatus",
    "softVersion",
}

ZENDURE_NUMBER_SETTINGS = {
    "socSet",
    "minSoc",
    "inverseMaxPower",
    "outputLimit",
    "inputLimit",
}

ZENDURE_SWITCH_SETTINGS = {
    "lampSwitch",
    "smartMode",
}

ZENDURE_SELECT_SETTINGS = {
    "acMode",
    "gridReverse",
    "gridOffMode",
}


class ZendureMqttManager:
    """Manage direct Zendure MQTT subscriptions and values."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the Zendure MQTT manager."""
        self.hass = hass

        # Structure:
        #
        # {
        #     "EEB4AEP1P040363": {
        #         "outputPackPower": 170.0,
        #         "packInputPower": 0.0,
        #         "electricLevel": 74.0,
        #         "packState": "charging",
        #     }
        # }
        self.values: dict[str, dict[str, MqttValue]] = {}
        self.number_values: dict[str, dict[str, MqttValue]] = {}
        self.switch_values: dict[str, dict[str, MqttValue]] = {}
        self.select_values: dict[str, dict[str, MqttValue]] = {}

        self._unsubscribers: list[Callable[[], None]] = []
        self._listeners: set[Callable[[], None]] = set()

    async def async_start(self) -> None:
        """Start listening to Zendure MQTT topics."""
        topics = (
            f"{ZENDURE_SENSOR_TOPIC}/+/+",
            f"{ZENDURE_NUMBER_TOPIC}/+/+",
            f"{ZENDURE_SWITCH_TOPIC}/+/+",
            f"{ZENDURE_SELECT_TOPIC}/+/+",
        )

        for topic in topics:
            unsubscribe = await mqtt.async_subscribe(
                self.hass,
                topic,
                self._async_message_received,
                qos=0,
            )
            self._unsubscribers.append(unsubscribe)

        _LOGGER.info(
            "Zendure MQTT manager gestart en luistert naar %s",
            ", ".join(topics),
        )

    async def _async_message_received(
        self,
        msg: ReceiveMessage,
    ) -> None:
        """Process an incoming Zendure MQTT message."""
        topic_parts = msg.topic.split("/")

        if len(topic_parts) != 4 or topic_parts[0] != "Zendure":
            return

        category = topic_parts[1]
        device_id = topic_parts[2]
        key = topic_parts[3]

        if category == "sensor":
            if key not in ZENDURE_MEASUREMENTS:
                return
            value = self._parse_sensor_value(key, msg.payload)
            target = self.values

        elif category == "number":
            if key not in ZENDURE_NUMBER_SETTINGS:
                return
            value = self._parse_number_value(msg.payload)
            target = self.number_values

        elif category == "switch":
            if key not in ZENDURE_SWITCH_SETTINGS:
                return
            value = self._parse_text_value(msg.payload)
            target = self.switch_values

        elif category == "select":
            if key not in ZENDURE_SELECT_SETTINGS:
                return
            value = self._parse_text_value(msg.payload)
            target = self.select_values

        else:
            return

        device_values = target.setdefault(device_id, {})
        device_values[key] = value

        for listener in list(self._listeners):
            listener()

        _LOGGER.debug(
            "Zendure MQTT ontvangen: categorie=%s, apparaat=%s, key=%s, waarde=%s",
            category,
            device_id,
            key,
            value,
        )

    @staticmethod
    def _parse_sensor_value(
        measurement: str,
        payload: str,
    ) -> MqttValue:
        """Convert a sensor MQTT payload to the appropriate value."""
        if measurement in TEXT_MEASUREMENTS:
            return str(payload).strip()

        try:
            return float(payload)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_number_value(payload: str) -> MqttValue:
        """Convert a number MQTT payload."""
        try:
            return float(payload)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_text_value(payload: str) -> str:
        """Convert a text MQTT payload."""
        return str(payload).strip()

    def async_add_listener(
        self,
        listener: Callable[[], None],
    ) -> Callable[[], None]:
        """Register a listener for MQTT value updates."""
        self._listeners.add(listener)

        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    def get_value(
        self,
        device_id: str,
        measurement: str,
    ) -> MqttValue:
        """Return a cached MQTT value."""
        return self.values.get(device_id, {}).get(measurement)

    def get_number_value(
        self,
        device_id: str,
        setting: str,
    ) -> MqttValue:
        """Return a cached Zendure number setting."""
        return self.number_values.get(device_id, {}).get(setting)

    def get_switch_value(
        self,
        device_id: str,
        setting: str,
    ) -> MqttValue:
        """Return a cached Zendure switch setting."""
        return self.switch_values.get(device_id, {}).get(setting)

    def get_select_value(
        self,
        device_id: str,
        setting: str,
    ) -> MqttValue:
        """Return a cached Zendure select setting."""
        return self.select_values.get(device_id, {}).get(setting)

    def get_control_snapshot(
        self,
        device_id: str,
    ) -> dict[str, dict[str, MqttValue]]:
        """Return all cached control values for a device."""
        return {
            "number": dict(self.number_values.get(device_id, {})),
            "switch": dict(self.switch_values.get(device_id, {})),
            "select": dict(self.select_values.get(device_id, {})),
        }

    def get_numeric_values(self, measurement: str) -> list[float]:
        """Return all valid numeric values for a measurement."""
        values: list[float] = []

        for device_values in self.values.values():
            value = device_values.get(measurement)

            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue

        return values

    def sum_measurement(self, measurement: str) -> float:
        """Return the sum of a measurement for all known devices."""
        return sum(self.get_numeric_values(measurement))

    def average_measurement(self, measurement: str) -> float | None:
        """Return the average of a measurement for all known devices."""
        values = self.get_numeric_values(measurement)

        if not values:
            return None

        return sum(values) / len(values)

    def min_measurement(self, measurement: str) -> float | None:
        """Return the lowest value of a measurement."""
        values = self.get_numeric_values(measurement)

        if not values:
            return None

        return min(values)

    def max_measurement(self, measurement: str) -> float | None:
        """Return the highest value of a measurement."""
        values = self.get_numeric_values(measurement)

        if not values:
            return None

        return max(values)

    def count_measurement(self, measurement: str) -> int:
        """Return the number of devices with a valid measurement."""
        return len(self.get_numeric_values(measurement))

    def get_text_values(self, measurement: str) -> list[str]:
        """Return all non-empty text values for a measurement."""
        values: list[str] = []

        for device_values in self.values.values():
            value = device_values.get(measurement)

            if value is None:
                continue

            text_value = str(value).strip()

            if text_value:
                values.append(text_value)

        return values

    def get_all_source_ids(self) -> set[str]:
        """Return every detected Zendure MQTT source ID."""
        return set(self.values)

    def get_device_ids(self) -> set[str]:
        """Return detected main SolarFlow device IDs.

        Battery-pack source IDs are excluded so pack telemetry does not
        increase the virtual battery device count.
        """
        return {
            source_id
            for source_id, measurements in self.values.items()
            if "electricLevel" in measurements
            or "packState" in measurements
        }

    def get_device_count(self) -> int:
        """Return the number of detected main SolarFlow devices."""
        return len(self.get_device_ids())

    async def async_stop(self) -> None:
        """Stop all Zendure MQTT subscriptions."""
        for unsubscribe in self._unsubscribers:
            unsubscribe()

        self._unsubscribers.clear()
        self._listeners.clear()

        _LOGGER.info("Zendure MQTT manager gestopt")


@dataclass(slots=True)
class HomeEnergyManagerRuntimeData:
    """Runtime data for Home Energy Manager."""

    source_entities: set[str]
    mqtt_manager: ZendureMqttManager


HomeEnergyManagerConfigEntry = ConfigEntry[HomeEnergyManagerRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeEnergyManagerConfigEntry,
) -> bool:
    """Set up Home Energy Manager from a config entry."""
    soc_entities = set(entry.data["soc_entities"])
    power_entities = set(entry.data.get("power_entities", []))

    mqtt_manager = ZendureMqttManager(hass)

    entry.runtime_data = HomeEnergyManagerRuntimeData(
        source_entities=soc_entities | power_entities,
        mqtt_manager=mqtt_manager,
    )

    await mqtt_manager.async_start()

    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: HomeEnergyManagerConfigEntry,
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )

    if unload_ok:
        await entry.runtime_data.mqtt_manager.async_stop()

    return unload_ok
