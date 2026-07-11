"""Base entity for Home Energy Manager."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN


class HomeEnergyManagerEntity:
    """Shared behavior for Home Energy Manager entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        source_entities: set[str],
    ) -> None:
        """Initialize the entity."""
        self._entry = entry
        self._source_entities = source_entities
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Virtuele batterij",
            manufacturer="Home Energy Manager",
            model="Virtuele batterij",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to source entity changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                list(self._source_entities),
                self._async_source_state_changed,
            )
        )

    @callback
    def _async_source_state_changed(
        self,
        event: Event[EventStateChangedData],
    ) -> None:
        """Handle a source entity state change."""
        self.async_write_ha_state()
