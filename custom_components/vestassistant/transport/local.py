"""Local API transport.

Talks straight to the board on the LAN: no cloud dependency, no rate limit,
and no server-side quiet hours to fight. Needs an enablement token from
Vestaboard, which is exchanged once for a long-lived API key.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from .base import Transport, VestaboardAuthError, VestaboardError, parse_grid

DEFAULT_PORT = 7000
TIMEOUT = aiohttp.ClientTimeout(total=10)


def base_url(host: str, port: int = DEFAULT_PORT) -> str:
    """``http://host:7000`` from whatever was typed.

    A bare host gets the scheme and the port; a URL keeps its scheme and gets
    the port only if it did not name one.
    """
    if "://" not in host:
        return f"http://{host}:{port}"
    parts = urlsplit(host.rstrip("/"))
    if parts.port is not None:
        return host.rstrip("/")
    return f"{parts.scheme}://{parts.hostname}:{port}"


class LocalTransport(Transport):
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

    @staticmethod
    async def async_enable(
        session: aiohttp.ClientSession,
        host: str,
        enablement_token: str,
        *,
        port: int = DEFAULT_PORT,
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
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise VestaboardError(
                f"could not reach the board at {host}: {err}"
            ) from err

        key = (data or {}).get("apiKey") if isinstance(data, dict) else None
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
                # Read the body rather than trusting Content-Length: a chunked
                # response has none, and a write comes back 201 with nothing.
                body = await resp.text()
                if not body.strip():
                    return None
                try:
                    return json.loads(body)
                except ValueError as err:
                    raise VestaboardError(
                        "the board returned something that is not JSON"
                    ) from err
        except aiohttp.ClientError as err:
            raise VestaboardError(f"could not reach the board: {err}") from err

    async def read(self) -> list[list[int]]:
        data = await self._request("GET")
        # vesta expects {"message": [...]}; the published docs show a bare
        # array. Accept both.
        layout = data.get("message") if isinstance(data, dict) else data
        grid = parse_grid(layout, "the board")
        self._note_geometry(grid)
        return grid

    async def write(self, characters: list[list[int]]) -> None:
        await self._request("POST", json=characters)
        self._note_geometry(characters)
