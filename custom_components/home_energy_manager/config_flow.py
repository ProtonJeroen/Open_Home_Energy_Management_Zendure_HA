"""Config flow for Home Energy Manager."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_BALANCE_THRESHOLD,
    CONF_CAPACITY_PER_DEVICE,
    CONF_POWER_ENTITIES,
    CONF_SOC_ENTITIES,
    DEFAULT_BALANCE_THRESHOLD,
    DEFAULT_CAPACITY_PER_DEVICE,
    DOMAIN,
)


class HomeEnergyManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Home Energy Manager."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            soc_entities = user_input[CONF_SOC_ENTITIES]
            if not soc_entities:
                errors["base"] = "no_soc_entities"
            else:
                return self.async_create_entry(
                    title="Virtuele batterij",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_SOC_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        multiple=True,
                    )
                ),
                vol.Optional(
                    CONF_POWER_ENTITIES,
                    default=[],
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        multiple=True,
                    )
                ),
                vol.Required(
                    CONF_CAPACITY_PER_DEVICE,
                    default=DEFAULT_CAPACITY_PER_DEVICE,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=100,
                        max=100000,
                        step=100,
                        unit_of_measurement="Wh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_BALANCE_THRESHOLD,
                    default=DEFAULT_BALANCE_THRESHOLD,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5,
                        max=25,
                        step=0.5,
                        unit_of_measurement="%",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
