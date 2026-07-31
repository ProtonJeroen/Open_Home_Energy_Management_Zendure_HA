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

ZENDURE_BASE_TOPIC = "Zendure/sensor"

ZENDURE_MEASUREMENTS = {
    "outputPackPower",
    "packInputPower",
    "outputHomePower",
    "electricLevel",
    "packState",
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

        self._unsubscribers: list[Callable[[], None]] = []
        self._listeners: set[Callable[[], None]] = set()

    async def async_start(self) -> None:
        """Start listening to Zendure MQTT topics."""
        topic = f"{ZENDURE_BASE_TOPIC}/+/+"

        unsubscribe = await mqtt.async_subscribe(
            self.hass,
            topic,
            self._async_message_received,
            qos=0,
        )

        self._unsubscribers.append(unsubscribe)

        _LOGGER.info(
            "Zendure MQTT manager gestart en luistert naar %s",
            topic,
        )

    async def _async_message_received(
        self,
        msg: ReceiveMessage,
    ) -> None:
        """Process an incoming Zendure MQTT message."""
        topic_parts = msg.topic.split("/")

        # Verwachte structuur:
        # Zendure/sensor/<device_id>/<measurement>
        if len(topic_parts) != 4:
            return

        if topic_parts[0] != "Zendure" or topic_parts[1] != "sensor":
            return

        device_id = topic_parts[2]
        measurement = topic_parts[3]

        # Negeer onderwerpen die Home Energy Manager nog niet gebruikt.
        if measurement not in ZENDURE_MEASUREMENTS:
            return

        value = self._parse_value(
            measurement,
            msg.payload,
        )

        device_values = self.values.setdefault(
            device_id,
            {},
        )
        device_values[measurement] = value

        for listener in list(self._listeners):
            listener()

        _LOGGER.debug(
            "Zendure MQTT ontvangen: apparaat=%s, meting=%s, waarde=%s",
            device_id,
            measurement,
            value,
        )

    @staticmethod
    def _parse_value(
        measurement: str,
        payload: str,
    ) -> MqttValue:
        """Convert an MQTT payload to the appropriate value."""
        if measurement == "packState":
            return str(payload).strip()

        try:
            return float(payload)
        except (TypeError, ValueError):
            return None

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

    def get_device_ids(self) -> set[str]:
        """Return all detected Zendure device IDs."""
        return set(self.values)

    def get_device_count(self) -> int:
        """Return the number of detected Zendure devices."""
        return len(self.values)

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
