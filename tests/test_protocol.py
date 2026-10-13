"""Protocol tests run with the Python standard library and no real card."""

import importlib.util
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "custom_components/scopedome_arduino/protocol.py"
spec = importlib.util.spec_from_file_location("scopedome_protocol", SOURCE)
protocol = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = protocol
spec.loader.exec_module(protocol)


def card(digital="1:1:1:0:1:1:1:1", relays="0:0:0:0:0.5:0:0:0:0", emergency="0"):
    """SDK 5.2 twelve-group card sample with meaningful contact bits."""
    return ";".join([
        digital, "12:20:30", "32000", "20:20:20:20:20:20:20:20:20",
        "1000:50", "0", "5", "0:0:0:0:0:0", relays,
        emergency, "12", "1",
    ])


def status(master=None, slave=None, flags="1:0:0:0"):
    return "getStatus|OK|" + "#".join([master or card(), slave or card(), flags])


class ProtocolTests(unittest.TestCase):
    def test_open_closed_and_between_depend_on_verified_polarity(self):
        data = protocol.parse_status(status())
        self.assertEqual(data.shutter_state(None), "unknown")
        self.assertEqual(data.shutter_state(0), "open")
        self.assertEqual(data.shutter_state(1), "closed")
        self.assertTrue(data.motion_safe)
        self.assertEqual(data.master.encoder, 32000)
        self.assertEqual(data.dome_motion, "stopped")
        self.assertEqual(data.shutter_motion, "stopped")

    def test_simultaneous_limit_contacts_are_fault(self):
        data = protocol.parse_status(status(slave=card(digital="1:1:1:0:0:1:1:1")))
        self.assertEqual(data.shutter_state(0), "fault")

    def test_offline_or_emergency_blocks_movement(self):
        offline = protocol.parse_status(status(flags="0:0:0:0"))
        self.assertFalse(offline.motion_safe)
        self.assertEqual(offline.shutter_state(0), "unknown")
        emergency = protocol.parse_status(status(master=card(emergency="1")))
        self.assertFalse(emergency.motion_safe)

    def test_motor_relays_report_direction_and_fault(self):
        moving = protocol.parse_status(status(master=card(relays="1:0:0:0:0.5:0:0:0:0"),
                                              slave=card(relays="0:1:0:0:0.5:0:0:0:0")))
        self.assertEqual(moving.dome_motion, "clockwise")
        self.assertEqual(moving.shutter_motion, "closing")
        fault = protocol.parse_status(status(master=card(relays="1:1:0:0:0.5:0:0:0:0")))
        self.assertEqual(fault.dome_motion, "fault")

    def test_movement_gate_rejects_unsafe_status(self):
        good = protocol.parse_status(status())
        self.assertTrue(good.validate_shutter_command("CLOSE", 0))
        self.assertFalse(good.validate_shutter_command("OPEN", 0))
        with self.assertRaises(protocol.MovementBlocked):
            good.validate_shutter_command("CLOSE", None)
        with self.assertRaises(protocol.MovementBlocked):
            protocol.parse_status(status(flags="0:0:0:0")).validate_shutter_command("CLOSE", 0)
        with self.assertRaises(protocol.MovementBlocked):
            protocol.parse_status(status(slave=card(emergency="2"))).validate_shutter_command("CLOSE", 0)
        with self.assertRaises(protocol.MovementBlocked):
            protocol.parse_status(status(slave=card(relays="1:0:0:0:0.5:0:0:0:0"))).validate_shutter_command("CLOSE", 0)

    def test_old_or_malformed_layout_is_rejected(self):
        for body in (
            "<html>login</html>", "getStatus|ERR|bad", "getStatus|OK|1:1;2:2#3:3",
            status(flags="2:0:0:0"), status(slave=card(digital="1:1:1")),
        ):
            with self.subTest(body=body[:30]), self.assertRaises(protocol.ProtocolError):
                protocol.parse_status(body)

    def test_wrong_command_acknowledgement_is_rejected(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.response_payload("getMac", "getMode|OK|master")


if __name__ == "__main__":
    unittest.main()
