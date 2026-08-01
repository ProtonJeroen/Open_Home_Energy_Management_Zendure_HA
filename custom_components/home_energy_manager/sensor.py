"""Sensor platform for Home Energy Manager."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_CAPACITY_PER_DEVICE
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
        NetBatteryPowerSensor(entry, source_entities),
        TotalChargePowerSensor(entry, source_entities),
        TotalDischargePowerSensor(entry, source_entities),
        VirtualPowerSensor(entry, source_entities),
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
        RemainingOutputTimeSensor(entry, source_entities),
    ]

    async_add_entities(entities)


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

