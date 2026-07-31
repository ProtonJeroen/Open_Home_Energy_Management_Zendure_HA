"""Sensor platform for Home Energy Manager."""

from __future__ import annotations

from statistics import mean
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_CAPACITY_PER_DEVICE,
    CONF_PACK_INPUT_ENTITIES,
    CONF_PACK_OUTPUT_ENTITIES,
    CONF_POWER_ENTITIES,
    CONF_SOC_ENTITIES,
    DOMAIN,
)

from .entity import HomeEnergyManagerEntity


def _numeric_states(
    hass: HomeAssistant,
    entity_ids: list[str],
) -> list[float]:
    """Return valid numeric states."""
    values: list[float] = []
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        if state is None or state.state in {"unknown", "unavailable"}:
            continue
        try:
            values.append(float(state.state))
        except (TypeError, ValueError):
            continue
    return values

def _sum_numeric_states(
    hass: HomeAssistant,
    entity_ids: list[str],
) -> float:
    """Return the sum of all valid numeric states."""
    return sum(_numeric_states(hass, entity_ids))
    
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Home Energy Manager sensors."""
    soc_entities = list(entry.data[CONF_SOC_ENTITIES])
    power_entities = list(entry.data.get(CONF_POWER_ENTITIES, []))
    pack_input_entities = list(
        entry.data.get(CONF_PACK_INPUT_ENTITIES, [])
    )
    pack_output_entities = list(
        entry.data.get(CONF_PACK_OUTPUT_ENTITIES, [])
    )

    source_entities = (
        set(soc_entities)
        | set(power_entities)
        | set(pack_input_entities)
        | set(pack_output_entities)
    )

    entities: list[SensorEntity] = [
        VirtualSocSensor(entry, source_entities, soc_entities),
        VirtualCapacitySensor(entry, source_entities, soc_entities),
        CurrentEnergySensor(entry, source_entities, soc_entities),
        ReserveEnergySensor(entry, source_entities, soc_entities),
        AvailableEnergySensor(entry, source_entities, soc_entities),
        BalanceSpreadSensor(entry, source_entities, soc_entities),
        OnlineDevicesSensor(entry, source_entities, soc_entities),
        VirtualStatusSensor(
            entry,
            source_entities,
            soc_entities,
            power_entities,
        ),
    ]

    if pack_input_entities and pack_output_entities:
        entities.append(
            NetBatteryPowerSensor(
                entry,
                source_entities,
                pack_input_entities,
                pack_output_entities,
            )
        )

    if pack_output_entities:
        entities.append(
            TotalChargePowerSensor(
                entry,
                source_entities,
                pack_output_entities,
            )
        )
    
    if power_entities:
        entities.append(
            VirtualPowerSensor(
                entry,
                source_entities,
                power_entities,
            )
        )

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


class VirtualSocSensor(BaseSensor):
    """Average state of charge."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery"

    def __init__(self, entry, source_entities, soc_entities) -> None:
        super().__init__(entry, source_entities, "soc", "Laadniveau")
        self._soc_entities = soc_entities

    @property
    def native_value(self) -> float | None:
        values = _numeric_states(self.hass, self._soc_entities)
        return round(mean(values), 1) if values else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "bron_entiteiten": self._soc_entities,
            "beschikbare_accus": len(_numeric_states(self.hass, self._soc_entities)),
            "totaal_accus": len(self._soc_entities),
        }


class VirtualCapacitySensor(BaseSensor):
    """Configured total nominal capacity."""

    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY_STORAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-high"

    def __init__(self, entry, source_entities, soc_entities) -> None:
        super().__init__(entry, source_entities, "capacity", "Nominale capaciteit")
        self._soc_entities = soc_entities
        self._capacity_per_device = float(entry.data[CONF_CAPACITY_PER_DEVICE])

    @property
    def native_value(self) -> float:
        return self._capacity_per_device * len(self._soc_entities)


class _EnergyMixin:
    """Shared calculations for virtual energy sensors."""

    RESERVE_PERCENTAGE = 20.0

    def _capacity_per_device(self) -> float:
        return float(self._entry.data[CONF_CAPACITY_PER_DEVICE])

    def _total_capacity(self) -> float:
        return self._capacity_per_device() * len(self._soc_entities)

    def _current_energy(self) -> float | None:
        values = _numeric_states(self.hass, self._soc_entities)
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

    def __init__(self, entry, source_entities, soc_entities) -> None:
        super().__init__(entry, source_entities, "current_energy", "Huidige energie")
        self._soc_entities = soc_entities

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

    def __init__(self, entry, source_entities, soc_entities) -> None:
        super().__init__(entry, source_entities, "reserve_energy", "Reserve-energie")
        self._soc_entities = soc_entities

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

    def __init__(self, entry, source_entities, soc_entities) -> None:
        super().__init__(entry, source_entities, "available_energy", "Beschikbare energie")
        self._soc_entities = soc_entities

    @property
    def native_value(self) -> float | None:
        current = self._current_energy()
        if current is None:
            return None
        reserve = self._total_capacity() * self.RESERVE_PERCENTAGE / 100.0
        return round(max(0.0, current - reserve), 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"reserve_percentage": self.RESERVE_PERCENTAGE}
        

class NetBatteryPowerSensor(BaseSensor):
    """Net battery power: positive is charging, negative is discharging."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-sync"

    def __init__(
        self,
        entry: ConfigEntry,
        source_entities: set[str],
        pack_input_entities: list[str],
        pack_output_entities: list[str],
    ) -> None:
        """Initialize the net battery power sensor."""
        super().__init__(
            entry,
            source_entities,
            "net_battery_power",
            "Netto batterijvermogen",
        )
        self._pack_input_entities = pack_input_entities
        self._pack_output_entities = pack_output_entities

    @property
    def native_value(self) -> float | None:
        input_values = _numeric_states(
            self.hass,
            self._pack_input_entities,
        )
        output_values = _numeric_states(
            self.hass,
            self._pack_output_entities,
        )

        if (
            len(input_values) != len(self._pack_input_entities)
            or len(output_values) != len(self._pack_output_entities)
        ):
            return None

        return round(
            sum(input_values) - sum(output_values),
            1,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "tekenrichting": "positief = laden, negatief = ontladen",
            "pack_input_entiteiten": self._pack_input_entities,
            "pack_output_entiteiten": self._pack_output_entities,
        }


class TotalChargePowerSensor(BaseSensor):
    """Total power currently charging all battery packs."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-plus"

    def __init__(
        self,
        entry: ConfigEntry,
        source_entities: set[str],
        output_pack_entities: list[str],
    ) -> None:
        """Initialize the total charge power sensor."""
        super().__init__(
            entry,
            source_entities,
            "total_charge_power",
            "Totaal laadvermogen",
        )
        self._output_pack_entities = output_pack_entities

    @property
    def native_value(self) -> float | None:
        """Return the total charging power from all Zendure devices."""
        mqtt_manager = self._entry.runtime_data.mqtt_manager
        value = mqtt_manager.sum_measurement("outputPackPower")
        return round(value, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "bron_entiteiten": self._output_pack_entities,
        }
        
        
class VirtualPowerSensor(BaseSensor):
    """Sum of battery power sensors."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"

    def __init__(self, entry, source_entities, power_entities) -> None:
        super().__init__(entry, source_entities, "power", "Totaal vermogen")
        self._power_entities = power_entities

    @property
    def native_value(self) -> float | None:
        values = _numeric_states(self.hass, self._power_entities)
        return round(sum(values), 1) if values else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"bron_entiteiten": self._power_entities}


class BalanceSpreadSensor(BaseSensor):
    """Difference between highest and lowest state of charge."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:scale-balance"

    def __init__(self, entry, source_entities, soc_entities) -> None:
        super().__init__(entry, source_entities, "balance_spread", "SoC-verschil")
        self._soc_entities = soc_entities

    @property
    def native_value(self) -> float | None:
        values = _numeric_states(self.hass, self._soc_entities)
        if not values:
            return None
        return round(max(values) - min(values), 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        states: dict[str, float | str] = {}
        for entity_id in self._soc_entities:
            state = self.hass.states.get(entity_id)
            states[entity_id] = state.state if state else "unavailable"
        return {"individuele_soc": states}


class OnlineDevicesSensor(BaseSensor):
    """Number of available battery devices."""

    _attr_icon = "mdi:access-point-check"

    def __init__(self, entry, source_entities, soc_entities) -> None:
        super().__init__(entry, source_entities, "online_devices", "Accu's online")
        self._soc_entities = soc_entities

    @property
    def native_value(self) -> int:
        return len(_numeric_states(self.hass, self._soc_entities))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"verwacht": len(self._soc_entities)}


class VirtualStatusSensor(BaseSensor):
    """Simple virtual battery status."""

    _attr_icon = "mdi:battery-sync"

    def __init__(
        self,
        entry,
        source_entities,
        soc_entities,
        power_entities,
    ) -> None:
        super().__init__(entry, source_entities, "status", "Status")
        self._soc_entities = soc_entities
        self._power_entities = power_entities

    @property
    def native_value(self) -> str:
        if len(_numeric_states(self.hass, self._soc_entities)) < len(self._soc_entities):
            return "degraded"
        if not self._power_entities:
            return "monitoring"
        values = _numeric_states(self.hass, self._power_entities)
        if not values:
            return "unknown"
        total = sum(values)
        if total > 10:
            return "charging_or_positive"
        if total < -10:
            return "discharging_or_negative"
        return "idle"
