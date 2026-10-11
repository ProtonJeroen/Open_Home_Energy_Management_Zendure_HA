"""Sensor platform for Home Energy Manager."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    RestoreSensor,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfElectricPotential, UnitOfEnergy, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_CAPACITY_PER_DEVICE,
    CONF_CONTROL_GAIN_PERCENT,
    CONF_GRID_DEAD_BAND_W,
    CONF_GRID_POWER_ENTITY,
    CONF_KNOWN_SOLARFLOW_IDS,
    CONF_MAX_POWER_PER_BATTERY_W,
    DEFAULT_GRID_DEAD_BAND_W,
    DEFAULT_CONTROL_GAIN_PERCENT,
    DEFAULT_MAX_POWER_PER_BATTERY_W,
    DOMAIN,
)
from .entity import HomeEnergyManagerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Home Energy Manager sensors with stable SolarFlow entities."""
    source_entities: set[str] = set()
    manager = entry.runtime_data.mqtt_manager

    def known_solarflow_device_ids() -> list[str]:
        """Return known full SolarFlow IDs without requiring live MQTT."""
        found: set[str] = {
            str(device_id)
            for device_id in entry.options.get(
                CONF_KNOWN_SOLARFLOW_IDS,
                [],
            )
        }
        found.update(str(device_id) for device_id in manager.get_device_ids())

        device_registry = dr.async_get(hass)
        for device_entry in dr.async_entries_for_config_entry(
            device_registry,
            entry.entry_id,
        ):
            if device_entry.manufacturer != "Zendure":
                continue

            for identifier_domain, identifier in device_entry.identifiers:
                if identifier_domain != DOMAIN:
                    continue
                identifier = str(identifier)
                if identifier.startswith("EEB4") and len(identifier) >= 6:
                    found.add(identifier)

        return sorted(found)

    device_ids = known_solarflow_device_ids()

    entities: list[SensorEntity] = [
        GridPowerSensor(entry, source_entities),
        DesiredBatteryPowerSensor(entry, source_entities),
        RegulatedBatteryPowerSensor(entry, source_entities),
        SolarFlowTargetPowerSensor(entry, source_entities, "040363"),
        SolarFlowTargetPowerSensor(entry, source_entities, "040453"),
        SolarFlowTargetPowerSensor(entry, source_entities, "040458"),
        VirtualSocSensor(entry, source_entities),
        VirtualCapacitySensor(entry, source_entities),
        CurrentEnergySensor(entry, source_entities),
        ReserveEnergySensor(entry, source_entities),
        AvailableEnergySensor(entry, source_entities),
        BalanceSpreadSensor(entry, source_entities),
        OnlineDevicesSensor(entry, source_entities),
        VirtualStatusSensor(entry, source_entities),
        PackStatusSensor(entry, source_entities),
        NetBatteryPowerSensor(entry, source_entities),
        TotalChargePowerSensor(entry, source_entities),
        TotalDischargePowerSensor(entry, source_entities),
        TotalChargedEnergySensor(entry, source_entities),
        TotalDischargedEnergySensor(entry, source_entities),
        VirtualPowerSensor(entry, source_entities),
        MqttControlsDiagnosticSensor(entry, source_entities),
        AggregateMeasurementSensor(
            entry,
            source_entities,
            key="pv_input_power",
            name="PV-ingangsvermogen",
            measurement="solarInputPower",
            aggregation="sum",
            unit=UnitOfPower.WATT,
            device_class=SensorDeviceClass.POWER,
            icon="mdi:solar-power",
        ),
        AggregateMeasurementSensor(
            entry,
            source_entities,
            key="ac_input_power",
            name="AC-ingangsvermogen",
            measurement="gridInputPower",
            aggregation="sum",
            unit=UnitOfPower.WATT,
            device_class=SensorDeviceClass.POWER,
            icon="mdi:transmission-tower-import",
        ),
        AggregateMeasurementSensor(
            entry,
            source_entities,
            key="home_output_power",
            name="Vermogen naar huis",
            measurement="outputHomePower",
            aggregation="sum",
            unit=UnitOfPower.WATT,
            device_class=SensorDeviceClass.POWER,
            icon="mdi:home-lightning-bolt",
        ),
        TextMeasurementSensor(
            entry,
            source_entities,
            key="heating_status",
            name="Verwarmingsstatus",
            measurement="heatState",
            icon="mdi:radiator",
        ),
        TextMeasurementSensor(
            entry,
            source_entities,
            key="soc_status",
            name="SoC-status",
            measurement="socStatus",
            icon="mdi:battery-heart-variant",
        ),
        MaxBatteryTemperatureSensor(entry, source_entities),
        HighestCellVoltageSensor(entry, source_entities),
        LowestCellVoltageSensor(entry, source_entities),
        CellVoltageSpreadSensor(entry, source_entities),
        RemainingOutputTimeSensor(entry, source_entities),
    ]

    # Create all five PV entities for every known SolarFlow immediately.
    # They no longer depend on whether a specific MQTT measurement happened
    # to be present during setup.
    for device_id in device_ids:
        for measurement, name, icon in (
            ("solarPower1", "PV ingang 1", "mdi:solar-panel"),
            ("solarPower2", "PV ingang 2", "mdi:solar-panel"),
            ("solarPower3", "PV ingang 3", "mdi:solar-panel"),
            ("solarPower4", "PV ingang 4", "mdi:solar-panel"),
            (
                "solarInputPower",
                "Totaal PV-ingangsvermogen",
                "mdi:solar-power",
            ),
        ):
            entities.append(
                SolarFlowPvPowerSensor(
                    entry,
                    device_id,
                    measurement,
                    name,
                    icon,
                )
            )

    async_add_entities(entities)

    # If MQTT is available, remember the full IDs for future starts where
    # Zendure HEMS may have disabled MQTT.
    live_ids = sorted(str(device_id) for device_id in manager.get_device_ids())
    if live_ids:
        current = list(
            entry.options.get(
                CONF_KNOWN_SOLARFLOW_IDS,
                [],
            )
        )
        if current != live_ids:
            new_options = dict(entry.options)
            new_options[CONF_KNOWN_SOLARFLOW_IDS] = live_ids
            hass.config_entries.async_update_entry(
                entry,
                options=new_options,
            )


class SolarFlowPvPowerSensor(RestoreSensor):
    """Stable power sensor for one physical SolarFlow PV input."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_available = True

    def __init__(
        self,
        entry: ConfigEntry,
        device_id: str,
        measurement: str,
        name: str,
        icon: str,
    ) -> None:
        """Initialize a physical SolarFlow PV sensor."""
        self._entry = entry
        self._device_id = device_id
        self._measurement = measurement
        self._last_value: float | None = None

        short_id = device_id[-6:]
        self._attr_unique_id = (
            f"{entry.entry_id}_{device_id}_{measurement}"
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

    def _read_mqtt_value(self) -> float | None:
        """Read a valid numeric value from the MQTT cache."""
        value = self.mqtt_manager.get_value(
            self._device_id,
            self._measurement,
        )
        try:
            return round(float(value), 1)
        except (TypeError, ValueError):
            return None

    @property
    def native_value(self) -> float | None:
        """Return live value, otherwise keep the last known value."""
        value = self._read_mqtt_value()
        if value is not None:
            self._last_value = value
        return self._last_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return source and availability information."""
        live_value = self._read_mqtt_value()
        return {
            "mqtt_meting": self._measurement,
            "solarflow_id": self._device_id,
            "mqtt_data_beschikbaar": live_value is not None,
            "waarde_status": (
                "live"
                if live_value is not None
                else "laatst bekende waarde"
            ),
        }

    async def async_added_to_hass(self) -> None:
        """Restore the previous value and subscribe to MQTT updates."""
        await super().async_added_to_hass()

        live_value = self._read_mqtt_value()
        if live_value is not None:
            self._last_value = live_value
        else:
            last_data = await self.async_get_last_sensor_data()
            if last_data is not None:
                try:
                    self._last_value = float(last_data.native_value)
                except (TypeError, ValueError):
                    self._last_value = None

        self.async_on_remove(
            self.mqtt_manager.async_add_listener(
                self._async_mqtt_updated
            )
        )

    @callback
    def _async_mqtt_updated(self) -> None:
        """Update only when a new valid MQTT value is available."""
        value = self._read_mqtt_value()
        if value is not None:
            self._last_value = value
        self.async_write_ha_state()


class BaseSensor(HomeEnergyManagerEntity, SensorEntity):
    """Base sensor."""

    def __init__(
        self,
        entry: ConfigEntry,
        source_entities: set[str],
        key: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(entry, source_entities)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name

    @property
    def mqtt_manager(self):
        """Return the shared Zendure MQTT manager."""
        return self._entry.runtime_data.mqtt_manager


class AggregateMeasurementSensor(BaseSensor):
    """Generic numeric MQTT measurement sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        entry: ConfigEntry,
        source_entities: set[str],
        *,
        key: str,
        name: str,
        measurement: str,
        aggregation: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
        icon: str,
    ) -> None:
        """Initialize an aggregate MQTT measurement sensor."""
        super().__init__(entry, source_entities, key, name)
        self._measurement = measurement
        self._aggregation = aggregation
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_icon = icon

    @property
    def native_value(self) -> float | None:
        """Return the aggregated MQTT value."""
        if self._aggregation == "sum":
            values = self.mqtt_manager.get_numeric_values(self._measurement)
            return round(sum(values), 2) if values else None

        if self._aggregation == "average":
            value = self.mqtt_manager.average_measurement(self._measurement)
        elif self._aggregation == "min":
            value = self.mqtt_manager.min_measurement(self._measurement)
        elif self._aggregation == "max":
            value = self.mqtt_manager.max_measurement(self._measurement)
        else:
            return None

        return round(value, 2) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return MQTT source information."""
        return {
            "mqtt_meting": self._measurement,
            "aggregatie": self._aggregation,
            "beschikbare_waarden": self.mqtt_manager.count_measurement(
                self._measurement
            ),
        }


class TextMeasurementSensor(BaseSensor):
    """Generic text MQTT measurement sensor."""

    def __init__(
        self,
        entry: ConfigEntry,
        source_entities: set[str],
        *,
        key: str,
        name: str,
        measurement: str,
        icon: str,
    ) -> None:
        """Initialize a text MQTT measurement sensor."""
        super().__init__(entry, source_entities, key, name)
        self._measurement = measurement
        self._attr_icon = icon

    @property
    def native_value(self) -> str | None:
        """Return unique text values."""
        values = sorted(set(self.mqtt_manager.get_text_values(self._measurement)))
        return ", ".join(values) if values else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return raw values by MQTT source."""
        source_values: dict[str, str] = {}

        for source_id in sorted(self.mqtt_manager.get_all_source_ids()):
            value = self.mqtt_manager.get_value(source_id, self._measurement)
            if value is not None:
                source_values[source_id] = str(value)

        return {
            "mqtt_meting": self._measurement,
            "bronwaarden": source_values,
        }


class MaxBatteryTemperatureSensor(BaseSensor):
    """Highest battery-pack temperature reported by Zendure."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer-high"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "max_battery_temperature",
            "Hoogste batterijtemperatuur",
        )

    @staticmethod
    def _to_celsius(value: float) -> float:
        """Convert Zendure maxTemp to degrees Celsius.

        Observed Zendure values such as 308.1 correspond to 34.95 °C,
        so maxTemp is treated as Kelvin.
        """
        return value - 273.15

    @property
    def native_value(self) -> float | None:
        """Return the highest reported battery temperature in °C."""
        values = self.mqtt_manager.get_numeric_values("maxTemp")

        if not values:
            return None

        return round(
            max(self._to_celsius(value) for value in values),
            1,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return raw maxTemp values for validation."""
        source_values: dict[str, dict[str, float]] = {}

        for source_id in sorted(self.mqtt_manager.get_all_source_ids()):
            raw = self.mqtt_manager.get_value(source_id, "maxTemp")

            try:
                raw_value = float(raw)
            except (TypeError, ValueError):
                continue

            source_values[source_id] = {
                "raw_kelvin": raw_value,
                "celsius": round(self._to_celsius(raw_value), 1),
            }

        return {
            "mqtt_meting": "maxTemp",
            "omrekening": "K - 273.15",
            "bronwaarden": source_values,
            "beschikbare_waarden": self.mqtt_manager.count_measurement(
                "maxTemp"
            ),
        }


class HighestCellVoltageSensor(BaseSensor):
    _attr_suggested_display_precision = 2
    """Highest cell voltage across all battery packs."""

    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-arrow-up"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "highest_cell_voltage",
            "Hoogste celspanning",
        )

    @property
    def native_value(self) -> float | None:
        value = self.mqtt_manager.max_measurement("maxVol")
        return round(value, 3) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        values: dict[str, float] = {}

        for source_id in sorted(self.mqtt_manager.get_all_source_ids()):
            raw = self.mqtt_manager.get_value(source_id, "maxVol")
            try:
                values[source_id] = round(float(raw), 3)
            except (TypeError, ValueError):
                continue

        return {
            "mqtt_meting": "maxVol",
            "bronwaarden": values,
            "beschikbare_waarden": self.mqtt_manager.count_measurement("maxVol"),
        }


class LowestCellVoltageSensor(BaseSensor):
    _attr_suggested_display_precision = 2
    """Lowest cell voltage across all battery packs."""

    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-arrow-down"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "lowest_cell_voltage",
            "Laagste celspanning",
        )

    @property
    def native_value(self) -> float | None:
        value = self.mqtt_manager.min_measurement("minVol")
        return round(value, 3) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        values: dict[str, float] = {}

        for source_id in sorted(self.mqtt_manager.get_all_source_ids()):
            raw = self.mqtt_manager.get_value(source_id, "minVol")
            try:
                values[source_id] = round(float(raw), 3)
            except (TypeError, ValueError):
                continue

        return {
            "mqtt_meting": "minVol",
            "bronwaarden": values,
            "beschikbare_waarden": self.mqtt_manager.count_measurement("minVol"),
        }


class CellVoltageSpreadSensor(BaseSensor):
    _attr_suggested_display_precision = 2
    """Largest per-pack cell-voltage spread."""

    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-bell-curve-cumulative"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "cell_voltage_spread",
            "Celspanningsverschil",
        )

    def _pack_spreads(self) -> dict[str, float]:
        spreads: dict[str, float] = {}

        for source_id in sorted(self.mqtt_manager.get_all_source_ids()):
            min_raw = self.mqtt_manager.get_value(source_id, "minVol")
            max_raw = self.mqtt_manager.get_value(source_id, "maxVol")

            try:
                min_value = float(min_raw)
                max_value = float(max_raw)
            except (TypeError, ValueError):
                continue

            spreads[source_id] = max(0.0, max_value - min_value)

        return spreads

    @property
    def native_value(self) -> float | None:
        spreads = self._pack_spreads()
        if not spreads:
            return None
        return round(max(spreads.values()), 3)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        spreads = self._pack_spreads()
        return {
            "berekening": "maxVol - minVol per batterijpack",
            "bronwaarden": {
                source_id: round(value, 3)
                for source_id, value in spreads.items()
            },
            "beschikbare_packs": len(spreads),
        }


class RemainingOutputTimeSensor(BaseSensor):
    """Average estimated remaining discharge time."""

    _attr_icon = "mdi:timer-sand"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "remaining_output_time",
            "Resterende ontlaadtijd",
        )

    @property
    def native_value(self) -> str | None:
        minutes = self.mqtt_manager.average_measurement(
            "remainOutTime"
        )

        if minutes is None:
            return None

        total_minutes = max(0, round(minutes))
        hours, remaining_minutes = divmod(total_minutes, 60)

        if hours:
            return f"{hours} u {remaining_minutes:02d} min"

        return f"{remaining_minutes} min"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        minutes = self.mqtt_manager.average_measurement(
            "remainOutTime"
        )

        if minutes is None:
            return {
                "mqtt_meting": "remainOutTime",
                "eenheid_bron": "minuten",
            }

        total_minutes = max(0, round(minutes))

        return {
            "mqtt_meting": "remainOutTime",
            "eenheid_bron": "minuten",
            "gemiddeld_aantal_minuten": total_minutes,
            "gemiddeld_aantal_uren": round(total_minutes / 60, 2),
            "beschikbare_waarden": self.mqtt_manager.count_measurement(
                "remainOutTime"
            ),
        }



class GridPowerSensor(BaseSensor):
    """Generic grid power input selected in integration options."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:transmission-tower"
    _attr_suggested_display_precision = 0

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "grid_power",
            "Netvermogen",
        )

    @property
    def grid_power_entity(self) -> str | None:
        """Return the configured grid power source entity."""
        return self._entry.options.get(
            CONF_GRID_POWER_ENTITY,
            self._entry.data.get(CONF_GRID_POWER_ENTITY),
        )

    @property
    def native_value(self) -> float | None:
        """Return grid power in W: positive import, negative export."""
        entity_id = self.grid_power_entity

        if not entity_id:
            return None

        state = self.hass.states.get(entity_id)

        if state is None or state.state in ("unknown", "unavailable"):
            return None

        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None

        unit = state.attributes.get("unit_of_measurement")

        if unit == "kW":
            value *= 1000.0

        return round(value, 1)

    async def async_added_to_hass(self) -> None:
        """Listen directly to the configured P1/grid-power entity."""
        await super().async_added_to_hass()

        entity_id = self.grid_power_entity
        if not entity_id:
            return

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [entity_id],
                self._async_grid_power_changed,
            )
        )

    @callback
    def _async_grid_power_changed(self, event) -> None:
        """Immediately mirror every source-entity state change."""
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "bron_entity": self.grid_power_entity,
            "tekenrichting": "positief = netafname, negatief = teruglevering",
            "update": "directe state-change listener",
        }


class DesiredBatteryPowerSensor(BaseSensor):
    """Desired battery power required to move grid power toward zero."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:target"
    _attr_suggested_display_precision = 0

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "desired_battery_power",
            "Gewenst batterijvermogen",
        )

    @property
    def grid_power_entity(self) -> str | None:
        """Return the configured grid power source entity."""
        return self._entry.options.get(
            CONF_GRID_POWER_ENTITY,
            self._entry.data.get(CONF_GRID_POWER_ENTITY),
        )

    def _grid_power_w(self) -> float | None:
        """Return grid power in W: positive import, negative export."""
        entity_id = self.grid_power_entity

        if not entity_id:
            return None

        state = self.hass.states.get(entity_id)

        if state is None or state.state in ("unknown", "unavailable"):
            return None

        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None

        if state.attributes.get("unit_of_measurement") == "kW":
            value *= 1000.0

        return value

    @property
    def native_value(self) -> float | None:
        """Return desired battery power.

        Positive = charge.
        Negative = discharge.
        """
        grid_power = self._grid_power_w()

        if grid_power is None:
            return None

        dead_band = float(
            self._entry.options.get(
                CONF_GRID_DEAD_BAND_W,
                DEFAULT_GRID_DEAD_BAND_W,
            )
        )

        if abs(grid_power) <= dead_band:
            return 0.0

        return round(-grid_power, 1)

    async def async_added_to_hass(self) -> None:
        """Listen directly to every grid-power source update."""
        await super().async_added_to_hass()

        entity_id = self.grid_power_entity
        if not entity_id:
            return

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [entity_id],
                self._async_grid_power_changed,
            )
        )

    @callback
    def _async_grid_power_changed(self, event) -> None:
        """Immediately recalculate desired battery power."""
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        grid_power = self._grid_power_w()

        return {
            "bron_netvermogen": self.grid_power_entity,
            "netvermogen_w": (
                round(grid_power, 1)
                if grid_power is not None
                else None
            ),
            "dode_zone_w": float(self._entry.options.get(CONF_GRID_DEAD_BAND_W, DEFAULT_GRID_DEAD_BAND_W)),
            "tekenrichting": "positief = laden, negatief = ontladen",
            "regelstrategie": "nul-op-de-meter, alleen berekening",
            "update": "directe state-change listener",
        }


class _GridControllerMixin:
    """Shared preview controller calculations."""

    FILTER_ALPHA = 0.75
    MAX_STEP_W = 800.0

    @property
    def grid_power_entity(self) -> str | None:
        return self._entry.options.get(
            CONF_GRID_POWER_ENTITY,
            self._entry.data.get(CONF_GRID_POWER_ENTITY),
        )

    def _grid_power_w(self) -> float | None:
        entity_id = self.grid_power_entity
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        if state.attributes.get("unit_of_measurement") == "kW":
            value *= 1000.0
        return value

    def _dead_band_w(self) -> float:
        return float(
            self._entry.options.get(
                CONF_GRID_DEAD_BAND_W,
                DEFAULT_GRID_DEAD_BAND_W,
            )
        )

    def _raw_target_w(self) -> float | None:
        grid_power = self._grid_power_w()
        if grid_power is None:
            return None
        if abs(grid_power) <= self._dead_band_w():
            return 0.0
        return -grid_power

    def _maximum_total_power_w(self) -> float:
        manager = self._entry.runtime_data.mqtt_manager
        device_ids = manager.get_device_ids()
        if not device_ids:
            return 0.0

        limits: list[float] = []
        for device_id in device_ids:
            value = manager.get_number_value(device_id, "inverseMaxPower")
            try:
                limits.append(float(value))
            except (TypeError, ValueError):
                limits.append(2400.0)
        return sum(max(0.0, value) for value in limits)

    def _next_regulated(self, current: float | None) -> float | None:
        raw = self._raw_target_w()
        if raw is None:
            return current

        control_gain = float(
            self._entry.options.get(
                CONF_CONTROL_GAIN_PERCENT,
                DEFAULT_CONTROL_GAIN_PERCENT,
            )
        ) / 100.0

        raw *= control_gain

        maximum = self._maximum_total_power_w()
        raw = max(-maximum, min(maximum, raw))

        if current is None:
            value = raw
        else:
            filtered = self.FILTER_ALPHA * raw + (1.0 - self.FILTER_ALPHA) * current
            delta = filtered - current
            delta = max(-self.MAX_STEP_W, min(self.MAX_STEP_W, delta))
            value = current + delta

        if abs(value) <= self._dead_band_w():
            value = 0.0

        return value


class RegulatedBatteryPowerSensor(_GridControllerMixin, BaseSensor):
    """Closed-loop battery target using actual battery power and P1 feedback."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:tune-vertical"
    _attr_suggested_display_precision = 0

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "regulated_battery_power",
            "Geregeld batterijvermogen",
        )
        self._regulated_w: float | None = 0.0

    def _known_solarflow_count(self) -> int:
        """Count physical SolarFlows from existing HA control entities."""
        entity_registry = er.async_get(self.hass)
        found: set[str] = set()

        for entity_entry in er.async_entries_for_config_entry(
            entity_registry,
            self._entry.entry_id,
        ):
            match = re.match(
                r"^(?:number|select)\.solarflow_(\d{6})_",
                entity_entry.entity_id,
            )
            if match is not None:
                found.add(match.group(1))

        return len(found)

    def _maximum_total_power_w(self) -> float:
        """Return configured maximum power for the complete battery system."""
        per_battery = float(
            self._entry.options.get(
                CONF_MAX_POWER_PER_BATTERY_W,
                DEFAULT_MAX_POWER_PER_BATTERY_W,
            )
        )
        return float(self._known_solarflow_count() * per_battery)

    def _actual_battery_power_w(self) -> float:
        """Return actual net battery power using the same sign as the target.

        Positive = charging, negative = discharging.
        """
        charge = self.mqtt_manager.sum_measurement("outputPackPower")
        discharge = self.mqtt_manager.sum_measurement("packInputPower")
        return float(charge - discharge)

    def _next_regulated(self) -> float | None:
        grid_power = self._grid_power_w()
        if grid_power is None:
            return self._regulated_w

        actual_battery = self._actual_battery_power_w()
        dead_band = self._dead_band_w()

        # Around zero, hold the actual battery power instead of accumulating
        # another correction. This prevents hunting around the setpoint.
        if abs(grid_power) <= dead_band:
            target = actual_battery
        else:
            gain = float(
                self._entry.options.get(
                    CONF_CONTROL_GAIN_PERCENT,
                    DEFAULT_CONTROL_GAIN_PERCENT,
                )
            ) / 100.0

            # P1 measures the complete house connection.
            #
            # Example:
            # actual battery = -700 W (discharging)
            # P1 grid import = +400 W
            # target at 100% = -700 - 400 = -1100 W
            #
            # This does not accumulate old targets, so repeated P1 updates
            # cannot run the target away to the configured maximum.
            target = actual_battery - (grid_power * gain)

        maximum = self._maximum_total_power_w()
        if maximum > 0:
            target = max(-maximum, min(maximum, target))

        # Limit a single command jump while preserving closed-loop feedback.
        if self._regulated_w is not None:
            delta = target - self._regulated_w
            delta = max(
                -self.MAX_STEP_W,
                min(self.MAX_STEP_W, delta),
            )
            target = self._regulated_w + delta

        return target

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        entity_id = self.grid_power_entity
        if entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [entity_id],
                    self._async_grid_power_changed,
                )
            )

        # Also refresh when actual Zendure battery feedback changes.
        self.async_on_remove(
            self.mqtt_manager.async_add_listener(
                self._async_mqtt_updated
            )
        )

    @callback
    def _async_grid_power_changed(self, event) -> None:
        self._regulated_w = self._next_regulated()
        self.async_write_ha_state()

    @callback
    def _async_mqtt_updated(self) -> None:
        self._regulated_w = self._next_regulated()
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        if self._regulated_w is None:
            return None
        return round(self._regulated_w, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        grid_power = self._grid_power_w()
        actual_battery = self._actual_battery_power_w()

        return {
            "netvermogen_w": (
                round(grid_power, 1)
                if grid_power is not None
                else None
            ),
            "werkelijk_batterijvermogen_w": round(
                actual_battery,
                1,
            ),
            "dode_zone_w": self._dead_band_w(),
            "correctiefactor_percent": float(
                self._entry.options.get(
                    CONF_CONTROL_GAIN_PERCENT,
                    DEFAULT_CONTROL_GAIN_PERCENT,
                )
            ),
            "regelprincipe": (
                "werkelijk batterijvermogen - P1 netafwijking"
            ),
            "max_stap_per_update_w": self.MAX_STEP_W,
            "max_vermogen_per_batterij_w": float(
                self._entry.options.get(
                    CONF_MAX_POWER_PER_BATTERY_W,
                    DEFAULT_MAX_POWER_PER_BATTERY_W,
                )
            ),
            "max_totaalvermogen_w": round(
                self._maximum_total_power_w(),
                1,
            ),
            "tekenrichting": (
                "positief = laden, negatief = ontladen"
            ),
            "modus": "5x P1 + echte batterijfeedback",
        }


class SolarFlowTargetPowerSensor(BaseSensor):
    """Preview target power for one SolarFlow."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:target"

    def __init__(self, entry, source_entities, short_id: str) -> None:
        self._short_id = short_id
        super().__init__(
            entry,
            source_entities,
            f"target_power_{short_id}",
            f"Doelvermogen {short_id}",
        )

    @property
    def grid_power_entity(self) -> str | None:
        return self._entry.options.get(
            CONF_GRID_POWER_ENTITY,
            self._entry.data.get(CONF_GRID_POWER_ENTITY),
        )

    def _solarflow_ids(self) -> list[str]:
        entity_registry = er.async_get(self.hass)
        found: set[str] = set()

        for entity_entry in er.async_entries_for_config_entry(
            entity_registry,
            self._entry.entry_id,
        ):
            match = re.match(
                r"^(?:number|select)\.solarflow_(\d{6})_",
                entity_entry.entity_id,
            )
            if match is not None:
                found.add(match.group(1))

        return sorted(found)

    def _regulated_total_w(self) -> float | None:
        """Read the regulated total directly from its entity if available."""
        for state in self.hass.states.async_all("sensor"):
            if (
                state.attributes.get("friendly_name")
                == "Battery System Geregeld batterijvermogen"
                or state.attributes.get("friendly_name")
                == "Geregeld batterijvermogen"
            ):
                try:
                    return float(state.state)
                except (TypeError, ValueError):
                    pass

        # Fallback to direct P1 calculation if entity lookup is not ready.
        grid_entity = self.grid_power_entity
        if not grid_entity:
            return None

        grid_state = self.hass.states.get(grid_entity)
        if grid_state is None or grid_state.state in (
            "unknown",
            "unavailable",
        ):
            return None

        try:
            grid_power_w = float(grid_state.state)
        except (TypeError, ValueError):
            return None

        if grid_state.attributes.get("unit_of_measurement") == "kW":
            grid_power_w *= 1000.0

        dead_band = float(
            self._entry.options.get(
                CONF_GRID_DEAD_BAND_W,
                DEFAULT_GRID_DEAD_BAND_W,
            )
        )

        if abs(grid_power_w) <= dead_band:
            return 0.0

        return -grid_power_w

    @property
    def native_value(self) -> float | None:
        total = self._regulated_total_w()
        ids = self._solarflow_ids()

        if total is None or self._short_id not in ids or not ids:
            return None

        per_battery = float(
            self._entry.options.get(
                CONF_MAX_POWER_PER_BATTERY_W,
                DEFAULT_MAX_POWER_PER_BATTERY_W,
            )
        )

        target = total / len(ids)
        target = max(-per_battery, min(per_battery, target))

        return round(target, 1)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        entity_id = self.grid_power_entity
        if not entity_id:
            return

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [entity_id],
                self._async_grid_power_changed,
            )
        )

    @callback
    def _async_grid_power_changed(self, event) -> None:
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "solarflow_id": self._short_id,
            "betekenis": "positief = laden, negatief = ontladen",
            "besturing_actief": False,
            "update": "directe P1 state-change listener",
            "bron": "Geregeld batterijvermogen",
            "stap": "5s preview",
        }


class VirtualSocSensor(BaseSensor):
    """Average state of charge."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(entry, source_entities, "soc", "Laadniveau")

    @property
    def native_value(self) -> float | None:
        value = self.mqtt_manager.average_measurement("electricLevel")
        return round(value, 1) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "beschikbare_accus": self.mqtt_manager.count_measurement(
                "electricLevel"
            ),
            "totaal_accus": self.mqtt_manager.get_device_count(),
            "mqtt_meting": "electricLevel",
        }


class VirtualCapacitySensor(BaseSensor):
    """Configured total nominal capacity."""

    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY_STORAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-high"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "capacity",
            "Nominale capaciteit",
        )
        self._capacity_per_device = float(
            entry.data[CONF_CAPACITY_PER_DEVICE]
        )

    @property
    def native_value(self) -> float:
        return (
            self._capacity_per_device
            * self.mqtt_manager.get_device_count()
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "capaciteit_per_accu": self._capacity_per_device,
            "aantal_accus": self.mqtt_manager.get_device_count(),
        }


class _EnergyMixin:
    """Shared calculations for virtual energy sensors."""

    RESERVE_PERCENTAGE = 20.0

    def _capacity_per_device(self) -> float:
        return float(self._entry.data[CONF_CAPACITY_PER_DEVICE])

    def _soc_values(self) -> list[float]:
        return self.mqtt_manager.get_numeric_values("electricLevel")

    def _total_capacity(self) -> float:
        return self._capacity_per_device() * len(self._soc_values())

    def _current_energy(self) -> float | None:
        values = self._soc_values()

        if not values:
            return None

        return sum(
            self._capacity_per_device()
            * max(0.0, min(100.0, soc))
            / 100.0
            for soc in values
        )


class CurrentEnergySensor(_EnergyMixin, BaseSensor):
    """Estimated energy currently stored in all batteries."""

    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY_STORAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-charging-80"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "current_energy",
            "Huidige energie",
        )

    @property
    def native_value(self) -> float | None:
        value = self._current_energy()
        return round(value, 0) if value is not None else None


class ReserveEnergySensor(_EnergyMixin, BaseSensor):
    """Energy reserved by the virtual battery."""

    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY_STORAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-lock"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "reserve_energy",
            "Reserve-energie",
        )

    @property
    def native_value(self) -> float:
        return round(
            self._total_capacity() * self.RESERVE_PERCENTAGE / 100.0,
            0,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"reserve_percentage": self.RESERVE_PERCENTAGE}


class AvailableEnergySensor(_EnergyMixin, BaseSensor):
    """Energy available above the configured reserve."""

    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY_STORAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-arrow-down"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "available_energy",
            "Beschikbare energie",
        )

    @property
    def native_value(self) -> float | None:
        current = self._current_energy()

        if current is None:
            return None

        reserve = (
            self._total_capacity()
            * self.RESERVE_PERCENTAGE
            / 100.0
        )
        return round(max(0.0, current - reserve), 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"reserve_percentage": self.RESERVE_PERCENTAGE}


class PackStatusSensor(BaseSensor):
    """Combined packState status for the physical SolarFlow devices."""

    _attr_icon = "mdi:battery-sync"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "pack_status",
            "Pack-status",
        )

    @property
    def native_value(self) -> str | None:
        """Return one shared state or 'mixed' when packs differ."""
        states: list[str] = []

        for device_id in sorted(self.mqtt_manager.get_device_ids()):
            value = self.mqtt_manager.get_value(device_id, "packState")

            if value is None:
                continue

            state = str(value).strip().lower()
            if state:
                states.append(state)

        if not states:
            return None

        unique_states = set(states)

        if len(unique_states) == 1:
            return states[0]

        return "mixed"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the individual pack states and counters."""
        individual: dict[str, str] = {}
        counts: dict[str, int] = {}

        for device_id in sorted(self.mqtt_manager.get_device_ids()):
            value = self.mqtt_manager.get_value(device_id, "packState")

            if value is None:
                individual[device_id] = "unavailable"
                continue

            state = str(value).strip().lower() or "unknown"
            individual[device_id] = state
            counts[state] = counts.get(state, 0) + 1

        return {
            "individuele_pack_status": individual,
            "charging": counts.get("charging", 0),
            "discharging": counts.get("discharging", 0),
            "idle": counts.get("idle", 0),
            "totaal_accus": self.mqtt_manager.get_device_count(),
        }


class NetBatteryPowerSensor(BaseSensor):
    """Net battery power: positive is charging."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-sync"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "net_battery_power",
            "Netto batterijvermogen",
        )

    @property
    def native_value(self) -> float:
        charge = self.mqtt_manager.sum_measurement("outputPackPower")
        discharge = self.mqtt_manager.sum_measurement("packInputPower")
        return round(charge - discharge, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "tekenrichting": "positief = laden, negatief = ontladen",
            "laadmeting": "outputPackPower",
            "ontlaadmeting": "packInputPower",
        }


class TotalChargePowerSensor(BaseSensor):
    """Total power currently charging all battery packs."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-plus"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "total_charge_power",
            "Totaal laadvermogen",
        )

    @property
    def native_value(self) -> float:
        return round(
            self.mqtt_manager.sum_measurement("outputPackPower"),
            1,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"mqtt_meting": "outputPackPower"}


class TotalDischargePowerSensor(BaseSensor):
    """Total power currently discharged by all battery packs."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-minus"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "total_discharge_power",
            "Totaal ontlaadvermogen",
        )

    @property
    def native_value(self) -> float:
        return round(
            self.mqtt_manager.sum_measurement("packInputPower"),
            1,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"mqtt_meting": "packInputPower"}


class CumulativeEnergySensor(
    HomeEnergyManagerEntity,
    RestoreSensor,
):
    """Integrate an MQTT power measurement into persistent energy."""

    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 3

    # Do not bridge long MQTT/restart gaps into artificial energy.
    _maximum_interval_seconds = 300.0

    def __init__(
        self,
        entry: ConfigEntry,
        source_entities: set[str],
        *,
        key: str,
        name: str,
        measurement: str,
        icon: str,
    ) -> None:
        """Initialize a cumulative energy sensor."""
        super().__init__(entry, source_entities)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._measurement = measurement
        self._attr_native_value = 0.0
        self._last_sample_time: datetime | None = None
        self._last_power_w: float | None = None

    @property
    def mqtt_manager(self):
        """Return the shared Zendure MQTT manager."""
        return self._entry.runtime_data.mqtt_manager

    async def async_added_to_hass(self) -> None:
        """Restore the total and start a fresh integration interval."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_sensor_data()

        if last_state is not None:
            try:
                restored_value = float(last_state.native_value)
            except (TypeError, ValueError):
                restored_value = 0.0

            self._attr_native_value = max(0.0, restored_value)

        self._last_sample_time = dt_util.utcnow()
        self._last_power_w = self._current_power()

    def _current_power(self) -> float:
        """Return current non-negative power for this energy direction."""
        return max(
            0.0,
            self.mqtt_manager.sum_measurement(self._measurement),
        )

    @callback
    def _async_mqtt_value_changed(self) -> None:
        """Integrate elapsed power and publish the updated total."""
        now = dt_util.utcnow()
        current_power_w = self._current_power()

        if (
            self._last_sample_time is not None
            and self._last_power_w is not None
        ):
            elapsed_seconds = (
                now - self._last_sample_time
            ).total_seconds()

            if 0.0 < elapsed_seconds <= self._maximum_interval_seconds:
                average_power_w = (
                    self._last_power_w + current_power_w
                ) / 2.0

                added_kwh = (
                    average_power_w
                    * elapsed_seconds
                    / 3_600_000.0
                )

                current_total = float(
                    self._attr_native_value or 0.0
                )
                new_total = round(
                    current_total + added_kwh,
                    6,
                )

                self._attr_native_value = max(
                    current_total,
                    new_total,
                )

        self._last_sample_time = now
        self._last_power_w = current_power_w
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return integration information."""
        return {
            "mqtt_meting": self._measurement,
            "berekening": "trapeziumintegratie van vermogen",
            "bronvermogen_w": round(self._current_power(), 1),
            "maximale_interval_seconden": (
                self._maximum_interval_seconds
            ),
        }


class TotalChargedEnergySensor(CumulativeEnergySensor):
    """Total energy charged into the virtual battery."""

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            key="total_charged_energy",
            name="Totale geladen energie",
            measurement="outputPackPower",
            icon="mdi:battery-arrow-up",
        )


class TotalDischargedEnergySensor(CumulativeEnergySensor):
    """Total energy discharged from the virtual battery."""

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            key="total_discharged_energy",
            name="Totale ontladen energie",
            measurement="packInputPower",
            icon="mdi:battery-arrow-down",
        )


class VirtualPowerSensor(BaseSensor):
    """Net power of the virtual battery."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "power",
            "Totaal vermogen",
        )

    @property
    def native_value(self) -> float:
        charge = self.mqtt_manager.sum_measurement("outputPackPower")
        discharge = self.mqtt_manager.sum_measurement("packInputPower")
        return round(charge - discharge, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "bron": "directe MQTT-cache",
            "tekenrichting": "positief = laden, negatief = ontladen",
        }


class MqttControlsDiagnosticSensor(BaseSensor):
    """Diagnostic view of cached Zendure control values."""

    _attr_icon = "mdi:tune-variant"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "mqtt_controls_diagnostic",
            "Zendure MQTT controls ontvangen",
        )

    @property
    def native_value(self) -> int:
        """Return the number of SolarFlow devices with control data."""
        device_ids = set(self.mqtt_manager.get_device_ids())
        device_ids.update(self.mqtt_manager.number_values)
        device_ids.update(self.mqtt_manager.switch_values)
        device_ids.update(self.mqtt_manager.select_values)

        return sum(
            1
            for device_id in device_ids
            if any(
                self.mqtt_manager.get_control_snapshot(device_id).values()
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all currently cached control values."""
        device_ids = set(self.mqtt_manager.get_device_ids())
        device_ids.update(self.mqtt_manager.number_values)
        device_ids.update(self.mqtt_manager.switch_values)
        device_ids.update(self.mqtt_manager.select_values)

        devices: dict[str, dict[str, dict[str, Any]]] = {}

        for device_id in sorted(device_ids):
            snapshot = self.mqtt_manager.get_control_snapshot(device_id)

            if any(snapshot.values()):
                devices[device_id] = snapshot

        return {
            "devices": devices,
            "aantal_apparaten_met_controls": len(devices),
            "verwachte_categorieen": [
                "number",
                "switch",
                "select",
            ],
        }


class BalanceSpreadSensor(BaseSensor):
    """Difference between highest and lowest state of charge."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:scale-balance"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "balance_spread",
            "SoC-verschil",
        )

    @property
    def native_value(self) -> float | None:
        lowest = self.mqtt_manager.min_measurement("electricLevel")
        highest = self.mqtt_manager.max_measurement("electricLevel")

        if lowest is None or highest is None:
            return None

        return round(highest - lowest, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        states: dict[str, float | str] = {}

        for device_id in sorted(self.mqtt_manager.get_device_ids()):
            value = self.mqtt_manager.get_value(
                device_id,
                "electricLevel",
            )
            states[device_id] = (
                value if value is not None else "unavailable"
            )

        return {"individuele_soc": states}


class OnlineDevicesSensor(BaseSensor):
    """Number of battery devices providing an SoC value."""

    _attr_icon = "mdi:access-point-check"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "online_devices",
            "Accu's online",
        )

    @property
    def native_value(self) -> int:
        return self.mqtt_manager.count_measurement("electricLevel")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "gedetecteerd": self.mqtt_manager.get_device_count(),
            "apparaat_ids": sorted(
                self.mqtt_manager.get_device_ids()
            ),
        }


class VirtualStatusSensor(BaseSensor):
    """Virtual battery status based on direct MQTT data."""

    _attr_icon = "mdi:battery-sync"

    def __init__(self, entry, source_entities) -> None:
        super().__init__(
            entry,
            source_entities,
            "status",
            "Status",
        )

    @property
    def native_value(self) -> str:
        device_count = self.mqtt_manager.get_device_count()
        soc_count = self.mqtt_manager.count_measurement(
            "electricLevel"
        )

        if device_count == 0:
            return "unknown"

        if soc_count < device_count:
            return "degraded"

        charge_power = self.mqtt_manager.sum_measurement(
            "outputPackPower"
        )
        discharge_power = self.mqtt_manager.sum_measurement(
            "packInputPower"
        )

        net_power = charge_power - discharge_power

        if net_power > 10:
            return "charging"

        if net_power < -10:
            return "discharging"

        states = {
            state.strip().lower()
            for state in self.mqtt_manager.get_text_values(
                "packState"
            )
        }

        if "discharging" in states:
            return "discharging"

        if "charging" in states:
            return "charging"

        return "idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        charge_power = self.mqtt_manager.sum_measurement(
            "outputPackPower"
        )
        discharge_power = self.mqtt_manager.sum_measurement(
            "packInputPower"
        )

        return {
            "pack_states": self.mqtt_manager.get_text_values(
                "packState"
            ),
            "laadvermogen": round(charge_power, 1),
            "ontlaadvermogen": round(discharge_power, 1),
            "netto_vermogen": round(
                charge_power - discharge_power,
                1,
            ),
            "bron": "directe MQTT-cache",
        }

