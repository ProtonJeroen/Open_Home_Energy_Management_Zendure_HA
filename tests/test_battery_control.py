"""Isolated controller regression tests; no HA installation or hardware needed."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


# Execute the actual controller class with only its HA boundary substituted.
SOURCE = Path(__file__).resolve().parents[1] / "custom_components/home_energy_manager/__init__.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
controller = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BatteryControlManager")
namespace = {
    "callback": lambda method: method,
    "DOMAIN": "home_energy_manager",
    "CONF_AUTOMATIC_BATTERY_CONTROL": "automatic_battery_control",
    "DEFAULT_AUTOMATIC_BATTERY_CONTROL": False,
    "CONF_MAX_POWER_PER_BATTERY_W": "max_power_per_battery_w",
    "DEFAULT_MAX_POWER_PER_BATTERY_W": 800,
    "_LOGGER": Mock(),
}
module = ast.Module(
    body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), controller],
    type_ignores=[],
)
exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
BatteryControlManager = namespace["BatteryControlManager"]


class BatteryControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry = {}
        self.subscriptions = []
        self.bus_listeners = []
        self.entry = SimpleNamespace(entry_id="entry", options={"automatic_battery_control": True})
        self.hass = SimpleNamespace(bus=SimpleNamespace(async_listen=self.listen))
        self.mqtt = SimpleNamespace(
            get_device_ids=lambda: {"EEB4AEP1P" + short for short in ("040363", "040453", "040458")},
            async_set_number_value=AsyncMock(),
        )
        namespace["er"] = SimpleNamespace(
            EVENT_ENTITY_REGISTRY_UPDATED="entity_registry_updated",
            async_get=lambda hass: SimpleNamespace(async_get_entity_id=lambda domain, platform, uid: self.registry.get((domain, platform, uid))),
        )
        namespace["async_track_state_change_event"] = self.track
        self.control = BatteryControlManager(self.hass, self.entry, self.mqtt)

    def listen(self, event_type, handler):
        self.bus_listeners.append(handler)
        return lambda: self.bus_listeners.remove(handler)

    def track(self, hass, ids, handler):
        subscription = (ids, handler)
        self.subscriptions.append(subscription)
        return lambda: self.subscriptions.remove(subscription)

    def register(self, short, entity_id, entry_id="entry"):
        self.registry[("sensor", "home_energy_manager", f"{entry_id}_target_power_{short}")] = entity_id

    async def change(self, entity_id, value):
        event = SimpleNamespace(data={"new_state": SimpleNamespace(entity_id=entity_id, state=value)})
        for ids, handler in list(self.subscriptions):
            if entity_id in ids:
                await handler(event)

    async def test_renamed_sensors_publish_for_all_three_devices(self):
        for short in ("040363", "040453", "040458"):
            self.register(short, f"sensor.battery_system_target_{short}_2")
        await self.control.async_start()
        for short in ("040363", "040453", "040458"):
            await self.change(f"sensor.battery_system_target_{short}_2", "-148")
            self.mqtt.async_set_number_value.assert_any_await("EEB4AEP1P" + short, "inputLimit", 0)
            self.mqtt.async_set_number_value.assert_any_await("EEB4AEP1P" + short, "outputLimit", 148)
        self.assertEqual(self.mqtt.async_set_number_value.await_count, 6)

    async def test_late_registration_rename_and_unload(self):
        await self.control.async_start()
        self.assertEqual(self.subscriptions, [])
        self.register("040363", "sensor.first")
        self.bus_listeners[0](None)
        await self.change("sensor.first", "-445")
        self.register("040363", "sensor.renamed")
        self.bus_listeners[0](None)
        self.assertEqual(len(self.subscriptions), 1)
        await self.change("sensor.first", "-500")
        self.assertEqual(self.mqtt.async_set_number_value.await_count, 2)
        await self.change("sensor.renamed", "-500")
        self.mqtt.async_set_number_value.assert_any_await("EEB4AEP1P040363", "outputLimit", 500)
        await self.control.async_stop()
        self.assertEqual(self.subscriptions, [])
        self.assertEqual(self.bus_listeners, [])

    async def test_disabled_invalid_foreign_and_missing_device_do_not_publish(self):
        self.register("040363", "sensor.ours")
        self.register("040453", "sensor.foreign", entry_id="other")
        await self.control.async_start()
        await self.change("sensor.foreign", "-445")
        for value in ("unknown", "unavailable", None):
            await self.change("sensor.ours", value)
        self.entry.options["automatic_battery_control"] = False
        await self.change("sensor.ours", "-445")
        self.entry.options["automatic_battery_control"] = True
        self.mqtt.get_device_ids = lambda: set()
        await self.change("sensor.ours", "-445")
        self.mqtt.async_set_number_value.assert_not_awaited()

    async def test_charge_clamp_and_duplicate_suppression_unchanged(self):
        self.register("040363", "sensor.ours")
        self.entry.options["max_power_per_battery_w"] = 800
        await self.control.async_start()
        await self.change("sensor.ours", "999")
        await self.change("sensor.ours", "999")
        self.assertEqual(self.mqtt.async_set_number_value.await_count, 2)
        self.mqtt.async_set_number_value.assert_any_await("EEB4AEP1P040363", "inputLimit", 800)
        self.mqtt.async_set_number_value.assert_any_await("EEB4AEP1P040363", "outputLimit", 0)
        await self.change("sensor.ours", "-999")
        self.mqtt.async_set_number_value.assert_any_await("EEB4AEP1P040363", "outputLimit", 800)


if __name__ == "__main__":
    unittest.main()
