"""Local API transport.

Talks straight to the board on the LAN: no cloud dependency, no rate limit,
and no server-side quiet hours to fight. Needs an enablement token from
Vestaboard, which is exchanged once for a long-lived API key.
"""

from __future__ import annotations

from typing import Any

import aiohttp

from .base import Transport, VestaboardAuthError, VestaboardError

DEFAULT_PORT = 7000
TIMEOUT = aiohttp.ClientTimeout(total=10)


def base_url(host: str, port: int = DEFAULT_PORT) -> str:
    if "://" in host:
        return host.rstrip("/")
    return f"http://{host}:{port}"


class LocalTransport(Transport):
    kind = "local"
    # The board imposes no write window of its own.
    server_side_quiet_hours = False

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        api_key: str,
        *,
        port: int = DEFAULT_PORT,
    ) -> None:
        super().__init__()
        self._session = session
        self._base = base_url(host, port)
        self._api_key = api_key
        self.firmware_version: str | None = None

    @staticmethod
    async def async_enable(
        session: aiohttp.ClientSession, host: str, enablement_token: str,
        *, port: int = DEFAULT_PORT,
    ) -> str:
        """Exchange an enablement token for a persistent local API key."""
        url = f"{base_url(host, port)}/local-api/enablement"
        try:
            async with session.post(
                url,
                headers={"X-Vestaboard-Local-Api-Enablement-Token": enablement_token},
                timeout=TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    raise VestaboardAuthError("the enablement token was rejected")
                if resp.status >= 400:
                    raise VestaboardError(f"HTTP {resp.status} enabling the local API")
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise VestaboardError(
                f"could not reach the board at {host}: {err}"
            ) from err

        key = data.get("apiKey")
        if not key:
            raise VestaboardError("the board did not return an API key")
        return key

    async def _request(self, method: str, **kw: Any) -> Any:
        url = f"{self._base}/local-api/message"
        try:
            async with self._session.request(
                method,
                url,
                headers={"X-Vestaboard-Local-Api-Key": self._api_key},
                timeout=TIMEOUT,
                **kw,
            ) as resp:
                if resp.status in (401, 403):
                    raise VestaboardAuthError("the board rejected the local API key")
                if resp.status >= 400:
                    raise VestaboardError(f"HTTP {resp.status} from the board")
                if server := resp.headers.get("Server"):
                    self.firmware_version = server.replace("Vestaboard/", "") or None
                if resp.status == 201 or resp.content_length in (0, None):
                    return None
                return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise VestaboardError(f"could not reach the board: {err}") from err

    async def read(self) -> list[list[int]]:
        data = await self._request("GET")
        grid = (data or {}).get("message") if isinstance(data, dict) else None
        if isinstance(grid, str):
            import json

            grid = json.loads(grid)
        if not isinstance(grid, list) or not grid:
            raise VestaboardError("the board returned no message")
        self._note_geometry(grid)
        return grid

    async def write(self, characters: list[list[int]]) -> None:
        await self._request("POST", json=characters)
        self._note_geometry(characters)
