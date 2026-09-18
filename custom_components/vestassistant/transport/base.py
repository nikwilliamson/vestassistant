"""Transport abstraction.

Two ways to reach a Vestaboard, with different capabilities. Everything above
this layer reads the capability attributes rather than asking which transport
it is, so the scheduler never has to know what a cloud is.

vesta's own clients are synchronous, so these are hand-rolled over aiohttp
using Home Assistant's shared session. vesta is still the dependency that
matters - it owns the character table - but not for HTTP.
"""

from __future__ import annotations

import abc
from datetime import timedelta
import json

from ..core.layout import Geometry, geometry_from_grid


class VestaboardError(Exception):
    """Any transport failure."""


class VestaboardAuthError(VestaboardError):
    """Credentials were rejected. Drives the reauth flow."""


class Transport(abc.ABC):
    """Read and write one board."""

    #: Minimum gap between writes. The cloud silently drops anything sent
    #: inside fifteen seconds of the previous message; the local API does not
    #: care. The coordinator enforces whatever this says.
    min_write_interval: timedelta = timedelta(0)

    #: Whether an all-blank grid can be written. The cloud refuses one
    #: outright, so where this is False the coordinator leaves the last card
    #: standing instead of trying to clear the board.
    supports_blank: bool = True

    #: Reported by the board where it says. The local API sends a Server
    #: header; the cloud says nothing.
    firmware_version: str | None = None

    def __init__(self) -> None:
        self._geometry: Geometry | None = None

    @property
    def geometry(self) -> Geometry | None:
        """Board dimensions, learned from the first successful read."""
        return self._geometry

    @abc.abstractmethod
    async def read(self) -> list[list[int]]:
        """Return the character grid currently on the board."""

    @abc.abstractmethod
    async def write(self, characters: list[list[int]]) -> None:
        """Write a character grid to the board."""

    async def async_detect_geometry(self) -> Geometry:
        """Read once to learn the board's shape.

        Neither API reports a model, but the grid dimensions are unambiguous:
        3x15 is a Note, 6x22 is a Flagship.
        """
        grid = await self.read()
        self._geometry = geometry_from_grid(grid)
        return self._geometry

    def _note_geometry(self, grid: list[list[int]]) -> None:
        if grid and self._geometry is None:
            self._geometry = geometry_from_grid(grid)


def parse_grid(value: object, what: str) -> list[list[int]]:
    """Coerce whatever an API handed back into a grid, or raise.

    Both APIs have at times returned the layout as a JSON string rather than
    an array, so a string is decoded before the shape check.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as err:
            raise VestaboardError(f"{what} returned an unreadable layout") from err
    if not isinstance(value, list) or not value:
        raise VestaboardError(f"{what} returned no layout")
    return value
