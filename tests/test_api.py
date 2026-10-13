"""Mock HTTP tests: no Home Assistant install and no network traffic."""

import asyncio
import importlib
from pathlib import Path
import sys
import types
import unittest


class FakeAuth:
    def __init__(self, user, password):
        self.user = user
        self.password = password


class FakeTimeout:
    def __init__(self, total):
        self.total = total


fake_aiohttp = types.ModuleType("aiohttp")
fake_aiohttp.BasicAuth = FakeAuth
fake_aiohttp.ClientError = type("ClientError", (Exception,), {})
fake_aiohttp.ClientSession = type("ClientSession", (), {})
fake_aiohttp.ClientTimeout = FakeTimeout
sys.modules["aiohttp"] = fake_aiohttp

package = types.ModuleType("scopedome_arduino_test")
package.__path__ = [str(Path(__file__).resolve().parents[1] /
                        "custom_components/scopedome_arduino")]
sys.modules[package.__name__] = package
api = importlib.import_module("scopedome_arduino_test.api")


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return self.body


class FakeSession:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(*self.answers.pop(0))


CARD_SAMPLE = (
    "1:1:1:0:1:1:1:1;12:20:30;32000;20:20:20:20:20:20:20:20:20;"
    "1000:50;0;5;0:0:0:0:0:0;0:0:0:0:0:0:0:0:0;0;12;1"
)
STATUS_SAMPLE = f"{CARD_SAMPLE}#{CARD_SAMPLE}#1:0:0:0"


class ApiTests(unittest.TestCase):
    def test_calibrated_rotation_reads_existing_positive_integer(self):
        for answer in ("getCalibratedRotation|OK|3240", "3240"):
            with self.subTest(answer=answer):
                session = FakeSession([(200, answer)])
                client = api.ScopeDomeClient(session, "192.0.2.1", 80, "secret")
                self.assertEqual(asyncio.run(client.calibrated_rotation()), 3240)
                self.assertTrue(session.calls[0][0].endswith("?getCalibratedRotation"))
        for answer in ("getCalibratedRotation|OK|0", "-1", "3240.5", "1000001",
                       "getCalibratedRotation|ERROR|unsupported"):
            with self.subTest(answer=answer), self.assertRaises(api.ProtocolError):
                client = api.ScopeDomeClient(FakeSession([(200, answer)]),
                                             "192.0.2.1", 80, "secret")
                asyncio.run(client.calibrated_rotation())

    def test_status_caches_calibration_and_refreshes_changed_span(self):
        status = STATUS_SAMPLE
        session = FakeSession([(200, status), (200, "getCalibratedRotation|OK|3240"),
                               (200, status), (200, status),
                               (200, "getCalibratedRotation|OK|6480")])
        client = api.ScopeDomeClient(session, "192.0.2.1", 80, "secret")
        self.assertEqual(asyncio.run(client.status()).calibrated_rotation, 3240)
        self.assertEqual(asyncio.run(client.status()).calibrated_rotation, 3240)
        self.assertEqual(len(session.calls), 3)
        client._next_calibration_read = 0
        self.assertEqual(asyncio.run(client.status()).calibrated_rotation, 6480)

    def test_optional_calibration_failure_preserves_status_and_manual_fallback(self):
        status = STATUS_SAMPLE
        for response in ((200, "getCalibratedRotation|OK|0"), (500, "unsupported")):
            with self.subTest(response=response):
                client = api.ScopeDomeClient(FakeSession([(200, status), response]),
                                             "192.0.2.1", 80, "secret")
                data = asyncio.run(client.status())
                self.assertEqual(data.master.encoder, 32000)
                self.assertIsNone(data.rotation_span())
                self.assertEqual(data.rotation_span(3240), 3240)
        client = api.ScopeDomeClient(FakeSession([(200, status), (401, "denied")]),
                                     "192.0.2.1", 80, "secret")
        with self.assertRaises(api.CardAuthError):
            asyncio.run(client.status())

    def test_detected_calibration_invalidates_cache_until_finished(self):
        calibrating = f"{CARD_SAMPLE}#{CARD_SAMPLE}#1:0:0:1"
        session = FakeSession([
            (200, STATUS_SAMPLE), (200, "getCalibratedRotation|OK|3240"),
            (200, calibrating), (200, STATUS_SAMPLE),
            (200, "getCalibratedRotation|OK|6480"),
        ])
        client = api.ScopeDomeClient(session, "192.0.2.1", 80, "secret")
        self.assertEqual(asyncio.run(client.status()).calibrated_rotation, 3240)
        self.assertIsNone(asyncio.run(client.status()).calibrated_rotation)
        self.assertEqual(asyncio.run(client.status()).calibrated_rotation, 6480)

    def test_identity_uses_read_only_http_with_basic_auth(self):
        session = FakeSession([(200, "getMode|OK|master"),
                               (200, "getMac|OK|DA:39:49:D4:FC:3C")])
        client = api.ScopeDomeClient(session, "192.0.2.1", 80, "secret")
        self.assertEqual(asyncio.run(client.identify()), ("master", "da3949d4fc3c"))
        self.assertEqual([call[0] for call in session.calls], [
            "http://192.0.2.1:80/?getMode", "http://192.0.2.1:80/?getMac"
        ])
        self.assertEqual(session.calls[0][1]["auth"].user, "scopedome")
        self.assertEqual(session.calls[0][1]["auth"].password, "secret")
        self.assertFalse(session.calls[0][1]["allow_redirects"])

    def test_only_documented_movement_commands_can_be_sent(self):
        session = FakeSession([(200, "moveShutter=OPEN|OK|"),
                               (200, "moveDome=CW:9|OK|")])
        client = api.ScopeDomeClient(session, "192.0.2.1", 80, "secret")
        asyncio.run(client.command("moveShutter=OPEN"))
        asyncio.run(client.command("moveDome=CW:9"))
        with self.assertRaises(ValueError):
            asyncio.run(client.command("clearEmergencys"))
        for unbounded in ("moveDome=CW", "moveDome=CW:0", "moveDome=CW:5001",
                          "moveDome=CW:9&clearEmergencys"):
            with self.subTest(unbounded=unbounded), self.assertRaises(ValueError):
                asyncio.run(client.command(unbounded))
        self.assertEqual(len(session.calls), 2)

    def test_auth_and_rejected_command_are_errors(self):
        unauthorized = api.ScopeDomeClient(FakeSession([(401, "")]), "192.0.2.1", 80, "bad")
        with self.assertRaises(api.CardAuthError):
            asyncio.run(unauthorized.identify())
        rejected = api.ScopeDomeClient(FakeSession([(200, "moveShutter=OPEN|ERROR|bad")]),
                                       "192.0.2.1", 80, "secret")
        with self.assertRaises(api.ProtocolError):
            asyncio.run(rejected.command("moveShutter=OPEN"))


if __name__ == "__main__":
    unittest.main()
