"""Strict parser for the documented ScopeDome Arduino 5.2 status format.

The manufacturer's SDK defines twelve semicolon-delimited groups per card.
Unknown or older layouts are rejected so they cannot drive physical controls.
"""

from dataclasses import dataclass
from math import isfinite


class ProtocolError(ValueError):
    """The card did not return the expected protocol data."""


class MovementBlocked(ValueError):
    """Current status does not permit the requested movement."""


EMERGENCY_REASONS = {
    0: "No alarm",
    1: "Digital input alarm",
    2: "Analog input alarm",
    3: "Cloud sensor alarm",
}


def emergency_reason(value: int) -> str:
    """Explain the SDK emergency code without guessing the physical trigger."""
    return EMERGENCY_REASONS.get(value, f"Unknown code {value}")


COMPASS_DIRECTIONS = (
    "North", "North-East", "East", "South-East",
    "South", "South-West", "West", "North-West",
)


def compass_direction(azimuth: float) -> str:
    """Name the nearest of eight compass directions for a calibrated angle."""
    return COMPASS_DIRECTIONS[int((azimuth % 360 + 22.5) // 45) % 8]


def azimuth_dms(azimuth: float) -> str:
    """Format a normalized azimuth in degrees, minutes, and whole seconds."""
    total_seconds = round((azimuth % 360) * 3600) % (360 * 3600)
    degrees, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{degrees}°{minutes:02d}′{seconds:02d}″"


def rotation_pulses(degrees: float, span: int | None) -> int | None:
    """Convert a bounded angle to a representable, bounded encoder step."""
    if (span is None or not isinstance(degrees, (int, float))
            or isinstance(degrees, bool) or not isfinite(degrees)
            or not 0 < degrees <= 10):
        return None
    pulses = min(round(degrees * span / 360), span // 36)
    return pulses if 1 <= pulses <= 5000 else None


def response_payload(command: str, body: str) -> str:
    """Read a command response, with or without its serial-style prefix."""
    value = body.strip()
    if not value or len(value) > 8192 or "<" in value or ">" in value:
        raise ProtocolError("Empty, oversized, or HTML command response")
    if "|" in value:
        parts = value.split("|", 2)
        if len(parts) != 3 or parts[0] != command or parts[1] != "OK":
            raise ProtocolError("Command response was not acknowledged")
        value = parts[2].strip()
    if not value or "\n" in value or "\r" in value:
        raise ProtocolError("Invalid command payload")
    return value


def _bits(group: str, minimum: int) -> tuple[int, ...]:
    try:
        values = tuple(int(item) for item in group.split(":"))
    except ValueError as exc:
        raise ProtocolError("Non-integer digital status") from exc
    if len(values) < minimum or any(value not in (0, 1) for value in values):
        raise ProtocolError("Invalid digital status width or value")
    return values


def _integers(group: str, minimum: int) -> tuple[int, ...]:
    try:
        values = tuple(int(item) for item in group.split(":"))
    except ValueError as exc:
        raise ProtocolError("Non-integer status") from exc
    if len(values) < minimum:
        raise ProtocolError("Invalid status width")
    return values


def _measurements(group: str, minimum: int) -> tuple[float | None, ...]:
    """Keep absent or malformed optional instruments from breaking card status."""
    values = []
    for item in group.split(":"):
        try:
            value = float(item)
        except ValueError:
            value = None
        values.append(value if value is not None and isfinite(value) else None)
    values.extend([None] * max(0, minimum - len(values)))
    return tuple(values)


def temperature(value: float | None) -> float | None:
    """Suppress impossible readings, including common disconnected-probe values."""
    return (value if value is not None and -100 <= value <= 150
            and abs(value - 99.99) > 0.005 else None)


def humidity(value: float | None) -> float | None:
    """Report a physically meaningful relative humidity only."""
    return (value if value is not None and 0 <= value <= 100
            and abs(value - 99.99) > 0.005 else None)


@dataclass(frozen=True)
class CardStatus:
    """Named fields needed by this integration; remaining groups stay opaque."""

    digital: tuple[int, ...]
    encoder: int
    relays: tuple[int, ...]
    emergency: int
    temperatures: tuple[float | None, ...]
    instruments: tuple[float | None, ...]
    outputs: tuple[float | None, ...]
    cloud_code: int | None

    @property
    def clouds(self) -> bool | None:
        """Any positive cloud-check code is an active card cloud alert."""
        return None if self.cloud_code is None else self.cloud_code > 0

    def heater_on(self, output_index: int) -> bool | None:
        """Read the named InBox or Motor relay without inferring its wiring."""
        value = self.outputs[output_index]
        return None if value not in (0, 1) else bool(value)


@dataclass(frozen=True)
class DomeStatus:
    master: CardStatus
    slave: CardStatus
    slave_online: bool
    finding_home: bool
    calibrated_rotation: int | None = None
    calibrating: bool = False

    def rotation_span(self, manual_fallback=None) -> int | None:
        """Prefer the card's measured span over the optional manual fallback."""
        value = self.calibrated_rotation or manual_fallback
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and isfinite(value) and value == int(value)
                and 1 <= value <= 1000000):
            return int(value)
        return None

    @property
    def dome_motion(self) -> str:
        cw, ccw = self.master.relays[:2]
        if cw and ccw:
            return "fault"
        if cw:
            return "clockwise"
        if ccw:
            return "counterclockwise"
        return "stopped"

    @property
    def shutter_motion(self) -> str:
        if not self.slave_online:
            return "unknown"
        opening, closing = self.slave.relays[:2]
        if opening and closing:
            return "fault"
        if opening:
            return "opening"
        if closing:
            return "closing"
        return "stopped"

    def shutter_state(self, active_level: int | None) -> str:
        """Infer a limit state only after the owner verifies contact polarity."""
        if active_level not in (0, 1) or not self.slave_online:
            return "unknown"
        opened = self.slave.digital[3] == active_level
        closed = self.slave.digital[4] == active_level
        if opened and closed:
            return "fault"
        if opened:
            return "open"
        if closed:
            return "closed"
        return "between"

    def at_home(self, active_level: int | None) -> bool | None:
        """Interpret the dome Home switch only after its polarity is verified."""
        if active_level not in (0, 1):
            return None
        return self.master.digital[2] == active_level

    def azimuth(self, counts_per_turn: int | None, home_count: int | None,
                home_azimuth: float | None, increasing_direction: str) -> float | None:
        """Convert encoder pulses only with user-supplied calibration."""
        if (not counts_per_turn or counts_per_turn <= 0 or home_count is None
                or home_azimuth is None):
            return None
        if increasing_direction not in ("cw", "ccw"):
            return None
        sign = 1 if increasing_direction == "cw" else -1
        return (home_azimuth + sign * (self.master.encoder - home_count)
                * 360 / counts_per_turn) % 360

    def at_park(self, azimuth: float | None, park_azimuth: float | None) -> bool | None:
        """Report proximity to the configured parking angle, not a card flag."""
        if azimuth is None or park_azimuth is None:
            return None
        difference = abs((azimuth - park_azimuth + 180) % 360 - 180)
        return difference <= 1 and self.dome_motion == "stopped"

    @property
    def motion_safe(self) -> bool:
        return self.slave_online and self.master.emergency == 0 and self.slave.emergency == 0

    def validate_shutter_command(self, direction: str, active_level: int | None) -> bool:
        """Return whether to send the command, or reject unsafe movement."""
        if direction not in ("OPEN", "CLOSE"):
            raise MovementBlocked("Unknown shutter direction")
        if active_level not in (0, 1):
            raise MovementBlocked("Verify shutter contact active level in integration options")
        if not self.motion_safe:
            raise MovementBlocked("Slave offline or emergency active; movement blocked")
        if self.calibrating:
            raise MovementBlocked("Dome encoder calibration is running")
        state = self.shutter_state(active_level)
        if state == "fault":
            raise MovementBlocked("Both shutter limit contacts are active")
        if self.shutter_motion == "fault":
            raise MovementBlocked("Both shutter motor relays are active")
        if direction == "OPEN" and self.shutter_motion == "closing":
            raise MovementBlocked("Shutter is closing; stop it before opening")
        if direction == "CLOSE" and self.shutter_motion == "opening":
            raise MovementBlocked("Shutter is opening; stop it before closing")
        if state == direction.lower():
            return False
        if self.shutter_motion == ("opening" if direction == "OPEN" else "closing"):
            return False
        return True

    def validate_dome_command(self, direction: str, *, allow_stop=False) -> bool:
        """Allow only a new, safe rotation direction from a fresh status."""
        if direction not in ("CW", "CCW"):
            raise MovementBlocked("Unknown dome direction")
        if not self.motion_safe:
            raise MovementBlocked("Shutter card offline or a safety alarm is active")
        if self.finding_home:
            raise MovementBlocked("Dome is finding Home")
        if self.calibrating:
            raise MovementBlocked("Dome encoder calibration is running")
        if self.dome_motion == "fault":
            raise MovementBlocked("Both dome motor relays are active")
        requested = "clockwise" if direction == "CW" else "counterclockwise"
        if self.dome_motion == requested and not allow_stop:
            return False
        if self.dome_motion != "stopped" and not allow_stop:
            raise MovementBlocked("Stop dome rotation before changing direction")
        return True


def _card(raw: str) -> CardStatus:
    groups = raw.split(";")
    if len(groups) != 12:
        raise ProtocolError(f"Expected 12 card status groups, got {len(groups)}")
    digital = _bits(groups[0], 8)
    encoder = _integers(groups[2], 1)[0]
    # Movement checks use the first two integer motor relays. Keep the
    # remaining heater, PWM, and free outputs separately as numeric readings.
    relays = _bits(":".join(groups[8].split(":")[:2]), 2)
    temperatures = _measurements(groups[3], 9)
    instruments = _measurements(groups[4], 2)
    outputs = _measurements(groups[8], 9)
    cloud_value = _measurements(groups[5], 1)[0]
    cloud_code = (int(cloud_value) if cloud_value is not None
                  and cloud_value >= 0 and cloud_value.is_integer() else None)
    emergency = _integers(groups[9], 1)[0]
    if emergency < 0:
        raise ProtocolError("Invalid emergency flag")
    return CardStatus(digital, encoder, relays, emergency,
                      temperatures, instruments, outputs, cloud_code)


def parse_status(body: str) -> DomeStatus:
    """Parse getStatus from a paired master/slave dome configuration."""
    parts = response_payload("getStatus", body).split("#")
    if len(parts) != 3:
        raise ProtocolError("Expected master, slave, and link flags")
    flags = _bits(parts[2], 4)
    return DomeStatus(_card(parts[0]), _card(parts[1]), bool(flags[0]), bool(flags[1]),
                      calibrating=bool(flags[3]))
