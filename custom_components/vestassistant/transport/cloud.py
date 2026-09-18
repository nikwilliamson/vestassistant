"""Cloud (Read/Write) API transport.

Works out of the box with a token from the Vestaboard developer console, at
the cost of a round trip through their cloud and a fifteen-second write
window.

Quiet hours are always bypassed here on purpose. The cloud enforces its own
quiet window by silently dropping posts, which would leave the board showing
something Vestassistant believes it has already replaced. We force every write
and apply the quiet policy locally instead, so board state and scheduler state
never diverge.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import aiohttp

from .base import Transport, VestaboardAuthError, VestaboardError

DEFAULT_URL = "https://cloud.vestaboard.com/"
TIMEOUT = aiohttp.ClientTimeout(total=20)


class CloudTransport(Transport):
    kind = "cloud"
    # "If you send more than 1 message every 15 seconds, you are likely to have
    # messages dropped." One extra second of headroom for clock skew.
    min_write_interval = timedelta(seconds=16)
    server_side_quiet_hours = True

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        *,
        base_url: str = DEFAULT_URL,
    ) -> None:
        super().__init__()
        self._session = session
        self._token = token
        self._base_url = base_url.rstrip("/") + "/"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-Vestaboard-Token": self._token,
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, url: str, **kw: Any) -> dict:
        try:
            async with self._session.request(
                method, url, headers=self._headers, timeout=TIMEOUT, **kw
            ) as resp:
                if resp.status in (401, 403):
                    raise VestaboardAuthError("Vestaboard rejected the API token")
                if resp.status >= 400:
                    body = await resp.text()
                    raise VestaboardError(f"HTTP {resp.status} from Vestaboard: {body}")
                if resp.content_type != "application/json":
                    return {}
                return await resp.json()
        except aiohttp.ClientError as err:
            raise VestaboardError(
                f"could not reach the Vestaboard cloud: {err}"
            ) from err

    async def read(self) -> list[list[int]]:
        data = await self._request("GET", self._base_url)
        message = data.get("currentMessage") or {}
        grid = message.get("layout")
        if isinstance(grid, str):
            # The cloud has historically returned the layout as a JSON string.
            import json

            grid = json.loads(grid)
        if not isinstance(grid, list) or not grid:
            raise VestaboardError("Vestaboard returned no layout")
        self._note_geometry(grid)
        return grid

    async def write(self, characters: list[list[int]]) -> None:
        await self._request(
            "POST",
            self._base_url,
            json={"characters": characters, "forced": True},
        )
        self._note_geometry(characters)
