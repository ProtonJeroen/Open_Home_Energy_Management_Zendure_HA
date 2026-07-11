"""Home Energy Manager integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS


@dataclass(slots=True)
class HomeEnergyManagerRuntimeData:
    """Runtime data for Home Energy Manager."""

    source_entities: set[str]


type HomeEnergyManagerConfigEntry = ConfigEntry[HomeEnergyManagerRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeEnergyManagerConfigEntry,
) -> bool:
    """Set up Home Energy Manager from a config entry."""
    soc_entities = set(entry.data["soc_entities"])
    power_entities = set(entry.data.get("power_entities", []))
    entry.runtime_data = HomeEnergyManagerRuntimeData(
        source_entities=soc_entities | power_entities
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: HomeEnergyManagerConfigEntry,
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
