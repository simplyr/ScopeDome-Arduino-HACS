"""HTTP transport for the card's documented query-command interface."""

import asyncio
import re

from aiohttp import BasicAuth, ClientError, ClientSession, ClientTimeout

from .const import HTTP_TIMEOUT
from .protocol import DomeStatus, ProtocolError, parse_status, response_payload


class CardAuthError(Exception):
    """HTTP credentials were rejected."""


class CardConnectionError(Exception):
    """The card could not be reached or returned an HTTP error."""


class ScopeDomeClient:
    """One connection to a Master card over its built-in HTTP server."""

    def __init__(self, session: ClientSession, host: str, port: int, password: str) -> None:
        self._session = session
        self._url = f"http://{host}:{port}/"
        self._auth = BasicAuth("scopedome", password)
        self._lock = asyncio.Lock()

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
                        raise CardConnectionError(f"HTTP {response.status}")
                    return await response.text()
            except (ClientError, asyncio.TimeoutError) as exc:
                raise CardConnectionError("Card did not respond") from exc

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
        return parse_status(await self._request("getStatus"))

    async def command(self, name: str) -> None:
        """Send only a fixed, documented movement or stop command."""
        if name not in {
            "moveShutter=OPEN", "moveShutter=CLOSE", "stopShutter", "stopDome"
        }:
            raise ValueError("Unsupported card command")
        answer = (await self._request(name)).strip()
        if not (answer == "OK" or answer == f"{name}|OK" or answer.startswith(f"{name}|OK|")):
            raise ProtocolError("Card did not acknowledge movement command")
