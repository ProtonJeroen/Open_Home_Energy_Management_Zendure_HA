"""Constants for Home Energy Manager."""

from typing import Final

DOMAIN: Final = "home_energy_manager"
PLATFORMS: Final = ["sensor", "binary_sensor", "select", "number"]

CONF_SOC_ENTITIES: Final = "soc_entities"
CONF_POWER_ENTITIES: Final = "power_entities"
CONF_CAPACITY_PER_DEVICE: Final = "capacity_per_device"
CONF_BALANCE_THRESHOLD: Final = "balance_threshold"
CONF_PACK_INPUT_ENTITIES = "pack_input_entities"
CONF_PACK_OUTPUT_ENTITIES = "pack_output_entities"

DEFAULT_CAPACITY_PER_DEVICE: Final = 2400.0
DEFAULT_BALANCE_THRESHOLD: Final = 3.0

CONF_GRID_POWER_ENTITY: Final = "grid_power_entity"
