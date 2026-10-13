"""Control sequencing and upgrade checks with a simulated card and registry."""

import asyncio
from dataclasses import replace
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class FakeEntity:
    def __init__(self, entry, coordinator, key):
        self.coordinator = coordinator
        self.key = key

    @property
    def available(self):
        return True

    async def async_added_to_hass(self):
        pass

    def async_write_ha_state(self):
        pass


class FakeRestoreNumber:
    async def async_get_last_number_data(self):
        return getattr(self, "restored", None)


package = types.ModuleType("scopedome_controls_test")
package.__path__ = [str(Path(__file__).resolve().parents[1] /
                        "custom_components/scopedome_arduino")]
entity = types.ModuleType(f"{package.__name__}.entity")
entity.ScopeDomeEntity = FakeEntity
button_module = types.ModuleType("homeassistant.components.button")
button_module.ButtonEntity = type("ButtonEntity", (), {})
number_module = types.ModuleType("homeassistant.components.number")
number_module.NumberMode = types.SimpleNamespace(BOX="box")
number_module.RestoreNumber = FakeRestoreNumber
exceptions = types.ModuleType("homeassistant.exceptions")
exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
helpers = types.ModuleType("homeassistant.helpers")
helpers.entity_registry = types.SimpleNamespace(async_get=lambda hass: hass.registry)

with patch.dict(sys.modules, {
    package.__name__: package,
    entity.__name__: entity,
    "homeassistant": types.ModuleType("homeassistant"),
    "homeassistant.components": types.ModuleType("homeassistant.components"),
    button_module.__name__: button_module,
    number_module.__name__: number_module,
    exceptions.__name__: exceptions,
    helpers.__name__: helpers,
}):
    button = importlib.import_module(f"{package.__name__}.button")
    number = importlib.import_module(f"{package.__name__}.number")
    protocol = importlib.import_module(f"{package.__name__}.protocol")


def status(relays="0:0", emergency=0):
    card = (
        "1:1:1:0:1:1:1:1;12:20:30;32000;20:20:20:20:20:20:20:20:20;"
        f"1000:50;0;5;0:0:0:0:0:0;{relays}:0:0:0:0:0:0:0;{emergency};12;1"
    )
    result = protocol.parse_status(f"{card}#{card}#1:0:0:0")
    return replace(result, calibrated_rotation=3240)


class Coordinator:
    def __init__(self, responses):
        self.responses = list(responses)
        self.data = self.responses[0]
        self.last_update_success = True
        self.rotation_angle = 9
        self.dome_stop_generation = 0
        self.dome_rotation_task = None
        self.movement_lock = asyncio.Lock()
        self.commands = []
        self.client = types.SimpleNamespace(command=self.command)
        self.waiting = asyncio.Event()
        self.release = asyncio.Event()

    async def command(self, command):
        self.commands.append(command)

    async def async_refresh(self):
        response = self.responses.pop(0)
        if response == "wait":
            self.waiting.set()
            await self.release.wait()
        elif isinstance(response, Exception):
            raise response
        else:
            self.data = response

    async def async_request_refresh(self):
        pass

    def async_update_listeners(self):
        pass


def entry(coordinator, options=None):
    return types.SimpleNamespace(runtime_data=coordinator, options=options or {},
                                 unique_id="card_mac", entry_id="entry_1")


class ControlsTests(unittest.IsolatedAsyncioTestCase):
    async def test_degrees_convert_to_exact_relative_commands(self):
        for angle, direction, pulses in ((9, "CCW", 81), (10, "CCW", 90), (1, "CW", 9)):
            with self.subTest(angle=angle, direction=direction):
                coordinator = Coordinator([status()])
                coordinator.rotation_angle = angle
                control = button.ScopeDomeRotate(entry(coordinator), coordinator,
                                                  direction, "Rotate", "icon")
                await control.async_press()
                self.assertEqual(coordinator.commands, [f"moveDome={direction}:{pulses}"])

    async def test_reverse_stops_and_confirms_before_moving(self):
        coordinator = Coordinator([status("0:1"), status()])
        coordinator.rotation_angle = 1
        control = button.ScopeDomeRotate(entry(coordinator), coordinator, "CW", "Right", "icon")
        await control.async_press()
        self.assertEqual(coordinator.commands, ["stopDome", "moveDome=CW:9"])

    async def test_no_reverse_on_timeout_or_new_alarm(self):
        for response in (TimeoutError(), status(emergency=3)):
            with self.subTest(response=response):
                coordinator = Coordinator([status("0:1"), response])
                control = button.ScopeDomeRotate(entry(coordinator), coordinator,
                                                  "CW", "Right", "icon")
                with self.assertRaises(exceptions.HomeAssistantError):
                    await control.async_press()
                self.assertEqual(coordinator.commands, ["stopDome"])

    async def test_manual_stop_cancels_waiting_reverse_request(self):
        coordinator = Coordinator([status("0:1"), "wait"])
        control = button.ScopeDomeRotate(entry(coordinator), coordinator, "CW", "Right", "icon")
        rotating = asyncio.create_task(control.async_press())
        await coordinator.waiting.wait()
        await button.ScopeDomeStopDome(entry(coordinator), coordinator).async_press()
        await rotating
        self.assertEqual(coordinator.commands, ["stopDome", "stopDome"])
        self.assertIsNone(coordinator.dome_rotation_task)

    async def test_disabled_angle_or_alarm_never_moves(self):
        for angle, data in ((0, status()), (11, status()), (1, status(emergency=1))):
            with self.subTest(angle=angle):
                coordinator = Coordinator([data])
                coordinator.rotation_angle = angle
                control = button.ScopeDomeRotate(entry(coordinator), coordinator,
                                                  "CW", "Right", "icon")
                with self.assertRaises(exceptions.HomeAssistantError):
                    await control.async_press()
                self.assertEqual(coordinator.commands, [])

    async def test_angle_input_restores_and_does_not_send_commands(self):
        coordinator = Coordinator([status()])
        control = number.ScopeDomeRotationAngle(entry(coordinator), coordinator)
        control.restored = types.SimpleNamespace(native_value=9)
        await control.async_added_to_hass()
        self.assertEqual(control.native_value, 9)
        await control.async_set_native_value(1)
        self.assertEqual(control.native_value, 1)
        self.assertEqual(coordinator.commands, [])
        with self.assertRaises(exceptions.HomeAssistantError):
            await control.async_set_native_value(11)

    async def test_previous_pulse_step_migrates_to_degrees(self):
        coordinator = Coordinator([status()])
        await number.async_setup_entry(None, entry(coordinator, {"rotation_step_pulses": 9}),
                                       lambda entities: None)
        self.assertEqual(coordinator.rotation_angle, 1)

    async def test_only_retired_buttons_for_this_entry_are_removed(self):
        removed = []
        records = {
            "custom_open": types.SimpleNamespace(config_entry_id="entry_1"),
            "custom_close": types.SimpleNamespace(config_entry_id="entry_1"),
            "other_stop": types.SimpleNamespace(config_entry_id="other_entry"),
        }
        lookup = {"card_mac_shutter_open": "custom_open",
                  "card_mac_shutter_close": "custom_close",
                  "card_mac_stop_shutter": "other_stop"}
        registry = types.SimpleNamespace(
            async_get_entity_id=lambda domain, platform, unique: lookup.get(unique),
            async_get=records.get, async_remove=removed.append,
        )
        coordinator = Coordinator([status()])
        added = []
        await button.async_setup_entry(types.SimpleNamespace(registry=registry),
                                       entry(coordinator), added.extend)
        self.assertEqual(removed, ["custom_open", "custom_close"])
        self.assertEqual([entity.key for entity in added], ["rotate_cw", "rotate_ccw", "stop_dome"])


if __name__ == "__main__":
    unittest.main()
