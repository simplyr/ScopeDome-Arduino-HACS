"""Strict parser for the documented ScopeDome Arduino 5.2 status format.

The manufacturer's SDK defines twelve semicolon-delimited groups per card.
Unknown or older layouts are rejected so they cannot drive physical controls.
"""

from dataclasses import dataclass


class ProtocolError(ValueError):
    """The card did not return the expected protocol data."""


class MovementBlocked(ValueError):
    """Current status does not permit a requested shutter movement."""


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


@dataclass(frozen=True)
class CardStatus:
    """Named fields needed by this integration; remaining groups stay opaque."""

    digital: tuple[int, ...]
    encoder: int
    relays: tuple[int, ...]
    emergency: int


@dataclass(frozen=True)
class DomeStatus:
    master: CardStatus
    slave: CardStatus
    slave_online: bool
    finding_home: bool

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


def _card(raw: str) -> CardStatus:
    groups = raw.split(";")
    if len(groups) != 12:
        raise ProtocolError(f"Expected 12 card status groups, got {len(groups)}")
    digital = _bits(groups[0], 8)
    encoder = _integers(groups[2], 1)[0]
    # PWM entries later in the group may be fractional; only motor relays
    # are needed here and are always the first two integer entries.
    relays = _bits(":".join(groups[8].split(":")[:2]), 2)
    emergency = _integers(groups[9], 1)[0]
    if emergency < 0:
        raise ProtocolError("Invalid emergency flag")
    return CardStatus(digital, encoder, relays, emergency)


def parse_status(body: str) -> DomeStatus:
    """Parse getStatus from a paired master/slave dome configuration."""
    parts = response_payload("getStatus", body).split("#")
    if len(parts) != 3:
        raise ProtocolError("Expected master, slave, and link flags")
    flags = _bits(parts[2], 4)
    return DomeStatus(_card(parts[0]), _card(parts[1]), bool(flags[0]), bool(flags[1]))
