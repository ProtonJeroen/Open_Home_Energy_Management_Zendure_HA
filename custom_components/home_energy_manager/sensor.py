"""Sensor platform for Home Energy Manager."""

from __future__ import annotations

from datetime import datetime
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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_CAPACITY_PER_DEVICE, DOMAIN
from .entity import HomeEnergyManagerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Home Energy Manager sensors from direct MQTT data."""
    source_entities: set[str] = set()

    entities: list[SensorEntity] = [
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

    async_add_entities(entities)

    manager = entry.runtime_data.mqtt_manager
    known_pv_entities: set[tuple[str, str]] = set()

    @callback
    def async_add_missing_pv_entities() -> None:
        """Create per-SolarFlow PV sensors when MQTT data is discovered."""
        new_entities: list[SensorEntity] = []

        for device_id in sorted(manager.get_device_ids()):
            device_values = manager.values.get(device_id, {})

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
                key = (device_id, measurement)

                if key in known_pv_entities:
                    continue

                if measurement not in device_values:
                    continue

                known_pv_entities.add(key)
                new_entities.append(
                    SolarFlowPvPowerSensor(
                        entry,
                        device_id,
                        measurement,
                        name,
                        icon,
                    )
                )

        if new_entities:
            async_add_entities(new_entities)

    remove_listener = manager.async_add_listener(
        async_add_missing_pv_entities
    )
    entry.async_on_unload(remove_listener)

    async_add_missing_pv_entities()


class SolarFlowPvPowerSensor(SensorEntity):
    """Power sensor for one physical SolarFlow PV input."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

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

    @property
    def native_value(self) -> float | None:
        """Return current PV power from direct MQTT feedback."""
        value = self.mqtt_manager.get_value(
            self._device_id,
            self._measurement,
        )

        try:
            return round(float(value), 1)
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return MQTT source information."""
        return {
            "mqtt_meting": self._measurement,
            "solarflow_id": self._device_id,
        }

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

