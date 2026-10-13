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


def card(digital="1:1:1:0:1:1:1:1", relays="0:0:0:0:0.5:0:0:0:0",
         emergency="0", encoder="32000",
         temperatures="20:20:20:20:20:20:20:20:20",
         instruments="1000:50", clouds="0"):
    """SDK 5.2 twelve-group card sample with meaningful contact bits."""
    return ";".join([
        digital, "12:20:30", encoder, temperatures,
        instruments, clouds, "5", "0:0:0:0:0:0", relays,
        emergency, "12", "1",
    ])


def status(master=None, slave=None, flags="1:0:0:0"):
    return "getStatus|OK|" + "#".join([master or card(), slave or card(), flags])


class ProtocolTests(unittest.TestCase):
    def test_weather_measurements_and_heater_relays(self):
        data = protocol.parse_status(status(
            master=card(
                temperatures="20:15:7:10:0:0:11:8:-18",
                instruments="1000:62.5", relays="0:0:1:1:0.5:0:0:0:0",
                clouds="2"),
            slave=card(
                temperatures="21:16:9:12:0:0:13:10:-16",
                instruments="1000:55.5", relays="0:0:0:1:0:0:0:0:0"),
        ))
        self.assertEqual(data.master.temperatures[2], 7)
        self.assertEqual(data.slave.temperatures[2], 9)
        self.assertEqual(data.slave.temperatures[8] - data.slave.temperatures[3], -28)
        self.assertEqual(data.slave.instruments[1], 55.5)
        self.assertTrue(data.master.clouds)
        self.assertEqual(data.master.cloud_code, 2)
        self.assertTrue(data.master.heater_on(2))
        self.assertTrue(data.master.heater_on(3))
        self.assertFalse(data.slave.heater_on(2))
        self.assertTrue(data.slave.heater_on(3))

    def test_driver_weather_readings_match_card_fields(self):
        # The driver's Internal Sensors screenshots show these card readings.
        data = protocol.parse_status(status(
            master=card(
                temperatures="30.55:33:19.87:nan:nan:nan:20.21:nan:nan",
                instruments="998:76.68", clouds="2", emergency="3"),
            slave=card(
                digital="1:1:1:1:0:1:0:1",
                temperatures="28.08:29:21.56:15.81:nan:nan:nan:38.58:-3.67",
                instruments="997:nan", clouds="1", emergency="1"),
        ))
        self.assertEqual(data.master.temperatures[2], 19.87)
        self.assertEqual(data.slave.temperatures[2], 21.56)
        self.assertAlmostEqual(data.slave.temperatures[8] - data.slave.temperatures[3],
                               -19.48)
        self.assertEqual(data.master.instruments[1], 76.68)
        self.assertEqual(data.master.cloud_code, 2)
        self.assertEqual(data.slave.cloud_code, 1)
        self.assertEqual(data.master.emergency, 3)
        self.assertEqual(data.slave.emergency, 1)
        self.assertEqual(data.slave.digital[5], 1)

    def test_missing_weather_probe_does_not_hide_card_status(self):
        data = protocol.parse_status(status(slave=card(
            temperatures="nan:bad:-127:20::20:20:20:999",
            instruments="1000:nan", clouds="bad",
        )))
        self.assertIsNone(data.slave.temperatures[0])
        self.assertIsNone(protocol.temperature(data.slave.temperatures[2]))
        self.assertIsNone(protocol.temperature(data.slave.temperatures[8]))
        self.assertIsNone(protocol.humidity(data.slave.instruments[1]))
        self.assertIsNone(data.slave.clouds)

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

    def test_home_and_azimuth_require_verified_installation_values(self):
        data = protocol.parse_status(status(master=card(encoder="32405")))
        self.assertIsNone(data.at_home(None))
        self.assertTrue(data.at_home(1))
        self.assertFalse(data.at_home(0))
        self.assertIsNone(data.azimuth(3240, None, 252.777778, "cw"))
        self.assertIsNone(data.azimuth(3240, 32000, 252.777778, "unknown"))
        self.assertAlmostEqual(data.azimuth(3240, 32000, 252.777778, "cw"),
                               (252.777778 + 45) % 360)
        self.assertAlmostEqual(data.azimuth(3240, 32000, 252.777778, "ccw"),
                               (252.777778 - 45) % 360)
        self.assertEqual(protocol.compass_direction(359), "North")
        self.assertEqual(protocol.compass_direction(90), "East")
        self.assertEqual(protocol.compass_direction(225), "South-West")
        self.assertIsNone(data.at_park(None, 220.33))
        self.assertTrue(data.at_park(220.33, 220.33))
        self.assertFalse(data.at_park(223, 220.33))

    def test_synchronized_driver_and_card_readings(self):
        # Driver: ENC -241 and 279°33'20"; card: raw encoder 32241.
        data = protocol.parse_status(status(
            master=card(digital="1:1:1:0:1:1:1:1", encoder="32241"),
            slave=card(digital="1:1:1:1:0:1:1:1"),
        ))
        azimuth = data.azimuth(3240, 32000, 252.777777777778, "cw")
        self.assertAlmostEqual(azimuth, 279 + 33 / 60 + 20 / 3600, places=5)
        self.assertEqual(protocol.compass_direction(azimuth), "West")
        self.assertFalse(data.at_park(azimuth, 220.33))
        self.assertFalse(data.at_home(0))
        self.assertEqual(data.shutter_state(0), "closed")

    def test_alarm_codes_are_explained_without_hiding_faults(self):
        self.assertEqual(protocol.emergency_reason(0), "No alarm")
        self.assertEqual(protocol.emergency_reason(1), "Digital input alarm")
        self.assertEqual(protocol.emergency_reason(2), "Analog input alarm")
        self.assertEqual(protocol.emergency_reason(3), "Cloud sensor alarm")
        self.assertEqual(protocol.emergency_reason(4), "Unknown code 4")

    def test_dome_rotation_gate_blocks_alarms_and_conflicting_motion(self):
        good = protocol.parse_status(status())
        self.assertTrue(good.validate_dome_command("CW"))
        moving = protocol.parse_status(status(master=card(
            relays="1:0:0:0:0.5:0:0:0:0")))
        self.assertFalse(moving.validate_dome_command("CW"))
        with self.assertRaises(protocol.MovementBlocked):
            moving.validate_dome_command("CCW")
        for unsafe in (
            protocol.parse_status(status(master=card(emergency="1"))),
            protocol.parse_status(status(slave=card(emergency="3"))),
            protocol.parse_status(status(flags="0:0:0:0")),
            protocol.parse_status(status(flags="1:1:0:0")),
            protocol.parse_status(status(master=card(
                relays="1:1:0:0:0.5:0:0:0:0"))),
        ):
            with self.subTest(unsafe=unsafe), self.assertRaises(protocol.MovementBlocked):
                unsafe.validate_dome_command("CW")

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
