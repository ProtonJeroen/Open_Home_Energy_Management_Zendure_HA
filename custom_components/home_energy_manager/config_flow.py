"""Config flow for Home Energy Manager."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CONTROL_GAIN_PERCENT,
    DEFAULT_CONTROL_GAIN_PERCENT,
    CONF_MAX_POWER_PER_BATTERY_W,
    DEFAULT_MAX_POWER_PER_BATTERY_W,
    CONF_AUTOMATIC_BATTERY_CONTROL,
    DEFAULT_AUTOMATIC_BATTERY_CONTROL,
    CONF_BALANCE_THRESHOLD,
    CONF_GRID_POWER_ENTITY,
    CONF_GRID_DEAD_BAND_W,
    CONF_CAPACITY_PER_DEVICE,
    CONF_PACK_INPUT_ENTITIES,
    CONF_PACK_OUTPUT_ENTITIES,
    CONF_POWER_ENTITIES,
    CONF_SOC_ENTITIES,
    DEFAULT_BALANCE_THRESHOLD,
    DEFAULT_CAPACITY_PER_DEVICE,
    DEFAULT_GRID_DEAD_BAND_W,
    DOMAIN,
)


class HomeEnergyManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Home Energy Manager."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return HomeEnergyManagerOptionsFlow()

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
                    title="Battery System",
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
                vol.Optional(
                    CONF_GRID_POWER_ENTITY,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        multiple=False,
                    )
                ),
                vol.Optional(
                    CONF_PACK_INPUT_ENTITIES,
                    default=[],
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        multiple=True,
                    )
                ),
                vol.Optional(
                    CONF_PACK_OUTPUT_ENTITIES,
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



class HomeEnergyManagerOptionsFlow(config_entries.OptionsFlow):
    """Handle Home Energy Manager options."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage Home Energy Manager options."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data=user_input,
            )

        current_grid_power_entity = self.config_entry.options.get(
            CONF_GRID_POWER_ENTITY,
            self.config_entry.data.get(CONF_GRID_POWER_ENTITY),
        )

        schema_dict: dict[Any, Any] = {}

        if current_grid_power_entity:
            schema_dict[
                vol.Optional(
                    CONF_GRID_POWER_ENTITY,
                    default=current_grid_power_entity,
                )
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    multiple=False,
                )
            )
        else:
            schema_dict[
                vol.Optional(CONF_GRID_POWER_ENTITY)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    multiple=False,
                )
            )

        current_dead_band = self.config_entry.options.get(
            CONF_GRID_DEAD_BAND_W,
            DEFAULT_GRID_DEAD_BAND_W,
        )

        schema_dict[
            vol.Optional(
                CONF_GRID_DEAD_BAND_W,
                default=current_dead_band,
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=500,
                step=10,
                unit_of_measurement="W",
                mode=selector.NumberSelectorMode.BOX,
            )
        )

        current_auto_control = self.config_entry.options.get(
            CONF_AUTOMATIC_BATTERY_CONTROL,
            DEFAULT_AUTOMATIC_BATTERY_CONTROL,
        )
        schema_dict[
            vol.Optional(
                CONF_AUTOMATIC_BATTERY_CONTROL,
                default=current_auto_control,
            )
        ] = selector.BooleanSelector()

        current_max_power_per_battery = self.config_entry.options.get(
            CONF_MAX_POWER_PER_BATTERY_W,
            DEFAULT_MAX_POWER_PER_BATTERY_W,
        )

        schema_dict[
            vol.Optional(
                CONF_MAX_POWER_PER_BATTERY_W,
                default=current_max_power_per_battery,
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=100,
                max=2400,
                step=50,
                unit_of_measurement="W",
                mode=selector.NumberSelectorMode.BOX,
            )
        )

        current_control_gain = self.config_entry.options.get(
            CONF_CONTROL_GAIN_PERCENT,
            DEFAULT_CONTROL_GAIN_PERCENT,
        )

        schema_dict[
            vol.Optional(
                CONF_CONTROL_GAIN_PERCENT,
                default=current_control_gain,
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10,
                max=100,
                step=5,
                unit_of_measurement="%",
                mode=selector.NumberSelectorMode.BOX,
            )
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
        )
