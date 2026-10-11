"""Home Energy Manager integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias

from homeassistant.components import mqtt
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_AUTOMATIC_BATTERY_CONTROL,
    CONF_GRID_POWER_ENTITY,
    CONF_MAX_POWER_PER_BATTERY_W,
    DEFAULT_AUTOMATIC_BATTERY_CONTROL,
    DEFAULT_MAX_POWER_PER_BATTERY_W,
    DOMAIN,
    PLATFORMS,
)

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

        # Zendure battery-pack topics sometimes repeat the device ID
        # in the measurement name, for example:
        # Zendure/sensor/JO2AEP1P0402415/JO2AEP1P0402415_maxTemp
        #
        # Normalize that to "maxTemp" so BMS measurements use the same
        # internal keys as the main SolarFlow measurements.
        prefixed_key = f"{device_id}_"
        if category == "sensor" and key.startswith(prefixed_key):
            key = key[len(prefixed_key):]

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

    async def async_set_number_value(
        self,
        device_id: str,
        setting: str,
        value: float,
    ) -> None:
        """Publish a Zendure number command."""
        if setting not in ZENDURE_NUMBER_SETTINGS:
            raise ValueError(
                f"Unsupported Zendure number setting: {setting}"
            )

        topic = (
            f"{ZENDURE_NUMBER_TOPIC}/"
            f"{device_id}/{setting}/set"
        )

        payload = str(int(value)) if float(value).is_integer() else str(value)

        await mqtt.async_publish(
            self.hass,
            topic,
            payload,
            qos=0,
            retain=False,
        )

        _LOGGER.info(
            "Zendure MQTT number opdracht verzonden: "
            "apparaat=%s, setting=%s, waarde=%s",
            device_id,
            setting,
            payload,
        )

    async def async_set_select_value(
        self,
        device_id: str,
        setting: str,
        value: str,
    ) -> None:
        """Publish a Zendure select command."""
        if setting not in ZENDURE_SELECT_SETTINGS:
            raise ValueError(
                f"Unsupported Zendure select setting: {setting}"
            )

        topic = (
            f"{ZENDURE_SELECT_TOPIC}/"
            f"{device_id}/{setting}/set"
        )

        await mqtt.async_publish(
            self.hass,
            topic,
            value,
            qos=0,
            retain=False,
        )

        _LOGGER.info(
            "Zendure MQTT opdracht verzonden: apparaat=%s, setting=%s, waarde=%s",
            device_id,
            setting,
            value,
        )

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
    battery_controller: object | None = None


HomeEnergyManagerConfigEntry = ConfigEntry[HomeEnergyManagerRuntimeData]


class BatteryControlManager:
    """Translate preview target power to Zendure input/output limits."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HomeEnergyManagerConfigEntry,
        mqtt_manager: ZendureMqttManager,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.mqtt_manager = mqtt_manager
        self._unsub: Callable[[], None] | None = None
        self._unsub_registry: Callable[[], None] | None = None
        self._target_entities: dict[str, str] = {}
        self._last_commands: dict[str, tuple[int, int]] = {}

    async def async_start(self) -> None:
        """Listen to target sensor state changes."""
        self._unsub_registry = self.hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            self._async_registry_updated,
        )
        self._async_refresh_target_entities()

    @callback
    def _async_registry_updated(self, event) -> None:
        """Follow target entities created or renamed after setup."""
        self._async_refresh_target_entities()

    @callback
    def _async_refresh_target_entities(self) -> None:
        """Resolve target sensor IDs using their stable unique IDs."""
        registry = er.async_get(self.hass)
        targets: dict[str, str] = {}
        for short_id in ("040363", "040453", "040458"):
            entity_id = registry.async_get_entity_id(
                "sensor", DOMAIN, f"{self.entry.entry_id}_target_power_{short_id}"
            )
            if entity_id is not None:
                targets[entity_id] = short_id

        if targets == self._target_entities:
            return
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._target_entities = targets
        if targets:
            self._unsub = async_track_state_change_event(
                self.hass, list(targets), self._async_target_changed
            )
        _LOGGER.debug("SolarFlow doelvermogen-koppelingen: %s", targets)

    async def async_stop(self) -> None:
        if self._unsub_registry:
            self._unsub_registry()
            self._unsub_registry = None
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._target_entities.clear()

    async def _async_target_changed(self, event) -> None:
        """Apply one changed target when automatic control is enabled."""
        if not self.entry.options.get(
            CONF_AUTOMATIC_BATTERY_CONTROL,
            DEFAULT_AUTOMATIC_BATTERY_CONTROL,
        ):
            return

        new_state = event.data.get("new_state")
        if new_state is None:
            return

        try:
            target = float(new_state.state)
        except (TypeError, ValueError):
            return

        short_id = self._target_entities.get(new_state.entity_id)
        if short_id is None:
            return
        full_id = next(
            (
                str(device_id)
                for device_id in self.mqtt_manager.get_device_ids()
                if str(device_id).endswith(short_id)
            ),
            None,
        )
        if full_id is None:
            _LOGGER.debug(
                "Geen live MQTT device voor SolarFlow %s; opdracht overgeslagen",
                short_id,
            )
            return

        # Positive target = charge, negative target = discharge.
        max_power = float(
            self.entry.options.get(
                CONF_MAX_POWER_PER_BATTERY_W,
                DEFAULT_MAX_POWER_PER_BATTERY_W,
            )
        )

        target = max(-max_power, min(max_power, target))

        input_limit = max(0, int(round(target)))
        output_limit = max(0, int(round(-target)))

        # Never leave charge and discharge limits active together.
        command = (input_limit, output_limit)
        if self._last_commands.get(full_id) == command:
            return

        await self.mqtt_manager.async_set_number_value(
            full_id,
            "inputLimit",
            input_limit,
        )
        await self.mqtt_manager.async_set_number_value(
            full_id,
            "outputLimit",
            output_limit,
        )
        self._last_commands[full_id] = command



async def async_update_options(
    hass: HomeAssistant,
    entry: HomeEnergyManagerConfigEntry,
) -> None:
    """Reload Home Energy Manager after options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeEnergyManagerConfigEntry,
) -> bool:
    """Set up Home Energy Manager from a config entry."""
    soc_entities = set(entry.data["soc_entities"])
    power_entities = set(entry.data.get("power_entities", []))

    grid_power_entity = entry.options.get(
        CONF_GRID_POWER_ENTITY,
        entry.data.get(CONF_GRID_POWER_ENTITY),
    )

    source_entities = soc_entities | power_entities
    if grid_power_entity:
        source_entities.add(grid_power_entity)

    mqtt_manager = ZendureMqttManager(hass)

    entry.runtime_data = HomeEnergyManagerRuntimeData(
        source_entities=source_entities,
        mqtt_manager=mqtt_manager,
    )

    entry.async_on_unload(
        entry.add_update_listener(async_update_options)
    )

    await mqtt_manager.async_start()

    battery_controller = BatteryControlManager(
        hass,
        entry,
        mqtt_manager,
    )
    entry.runtime_data.battery_controller = battery_controller

    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )

    await battery_controller.async_start()

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
        controller = entry.runtime_data.battery_controller
        if controller is not None:
            await controller.async_stop()
        await entry.runtime_data.mqtt_manager.async_stop()

    return unload_ok

