"""HTTP transport for the card's documented query-command interface."""

import asyncio
from dataclasses import replace
import logging
import re
from time import monotonic

from aiohttp import BasicAuth, ClientError, ClientSession, ClientTimeout

from .const import HTTP_TIMEOUT
from .protocol import (
    MAX_DOME_COMMAND_PULSES, DomeStatus, ProtocolError, parse_status, response_payload,
)

_LOGGER = logging.getLogger(__name__)
CALIBRATION_REFRESH_SECONDS = 300
STATUS_RETRY_DELAY = 0.5


class CardAuthError(Exception):
    """HTTP credentials were rejected."""


class CardConnectionError(Exception):
    """The card could not be reached or returned an HTTP error."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ScopeDomeClient:
    """One connection to a Master card over its built-in HTTP server."""

    def __init__(self, session: ClientSession, host: str, port: int, password: str) -> None:
        self._session = session
        self._url = f"http://{host}:{port}/"
        self._auth = BasicAuth("scopedome", password)
        self._lock = asyncio.Lock()
        self._calibrated_rotation = None
        self._next_calibration_read = 0.0

    async def _request(self, command: str) -> str:
        async with self._lock:
            try:
                async with self._session.get(
                    f"{self._url}?{command}",
                    auth=self._auth,
                    timeout=ClientTimeout(total=HTTP_TIMEOUT),
                    allow_redirects=False,
                ) as response:
                    if response.status == 401:
                        raise CardAuthError("HTTP authentication failed")
                    if response.status != 200:
                        raise CardConnectionError(
                            f"Card returned HTTP {response.status}",
                            retryable=response.status in {408, 429, 500, 502, 503, 504},
                        )
                    return await response.text()
            except asyncio.TimeoutError as exc:
                raise CardConnectionError(
                    f"Card request timed out after {HTTP_TIMEOUT} seconds",
                    retryable=True,
                ) from exc
            except ClientError as exc:
                raise CardConnectionError(
                    f"Card connection failed ({type(exc).__name__})",
                    retryable=True,
                ) from exc

    async def identify(self) -> tuple[str, str]:
        """Return mode and hardware MAC. Reads only."""
        mode = response_payload("getMode", await self._request("getMode")).lower()
        if mode != "master":
            raise ProtocolError(f"Expected a dome Master card, got {mode!r}")
        mac = response_payload("getMac", await self._request("getMac"))
        normalized = re.sub(r"[:-]", "", mac).lower()
        if not re.fullmatch(r"[0-9a-f]{12}", normalized):
            raise ProtocolError("Invalid card MAC address")
        return mode, normalized

    async def status(self) -> DomeStatus:
        """Retry a transient read once; never return cached status after failure."""
        try:
            status = parse_status(await self._request("getStatus"))
        except CardConnectionError as exc:
            if not exc.retryable:
                raise
            _LOGGER.debug("Retrying getStatus after a transient failure: %s", exc)
            # The request lock is released during the delay so Stop can run.
            await asyncio.sleep(STATUS_RETRY_DELAY)
            status = parse_status(await self._request("getStatus"))
        if status.calibrating:
            self._calibrated_rotation = None
            self._next_calibration_read = 0.0
            return status
        if monotonic() >= self._next_calibration_read:
            self._next_calibration_read = monotonic() + CALIBRATION_REFRESH_SECONDS
            try:
                self._calibrated_rotation = await self.calibrated_rotation()
            except (CardConnectionError, ProtocolError):
                self._calibrated_rotation = None
                _LOGGER.debug("Automatic encoder calibration is unavailable")
        return replace(status, calibrated_rotation=self._calibrated_rotation)

    async def calibrated_rotation(self) -> int:
        """Read an existing calibration without starting a calibration movement."""
        payload = response_payload(
            "getCalibratedRotation", await self._request("getCalibratedRotation")
        )
        if not re.fullmatch(r"[0-9]+", payload) or not 1 <= int(payload) <= 1000000:
            raise ProtocolError("Card has no valid calibrated rotation span")
        return int(payload)

    async def command(self, name: str) -> None:
        """Send only documented movements with bounded dome rotation."""
        if name not in {
            "moveShutter=OPEN", "moveShutter=CLOSE", "stopShutter", "stopDome", "findHome"
        } and not (
            (match := re.fullmatch(r"moveDome=(CW|CCW):([1-9][0-9]{0,5})", name))
            and int(match.group(2)) <= MAX_DOME_COMMAND_PULSES
        ):
            raise ValueError("Unsupported card command")
        answer = (await self._request(name)).strip()
        if not (answer == "OK" or answer == f"{name}|OK" or answer.startswith(f"{name}|OK|")):
            raise ProtocolError("Card did not acknowledge movement command")
