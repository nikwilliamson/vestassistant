"""A picture of the board.

Rendered as SVG rather than a raster, which keeps Pillow out of the
dependency list - the integration needs exactly one requirement, and it is
the character table.
"""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import VestassistantConfigEntry
from .core.layout import PRINTABLE
from .entity import VestassistantEntity

# Vestaboard colour codes 63-69.
SWATCH = {
    63: "#da2f2b",
    64: "#e6791f",
    65: "#efc51c",
    66: "#3aa14a",
    67: "#2b6cd4",
    68: "#7a3fb5",
    69: "#f2f2f2",
    70: "#101010",
    71: "#101010",
}


#: Every read and write goes through the one coordinator, which
#: serialises them and enforces the board's own spacing, so there is
#: nothing here for Home Assistant to throttle.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestassistantConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([BoardImage(hass, entry.runtime_data)])


class BoardImage(VestassistantEntity, ImageEntity):
    _attr_content_type = "image/svg+xml"
    _attr_name = None

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        VestassistantEntity.__init__(self, coordinator, "board")
        ImageEntity.__init__(self, hass)
        self._attr_image_last_updated = dt_util.utcnow()

    def _handle_coordinator_update(self) -> None:
        self._attr_image_last_updated = dt_util.utcnow()
        self._cached_image = None
        super()._handle_coordinator_update()

    def image(self) -> bytes | None:
        grid = self.coordinator.data
        if not grid:
            return None
        return _svg(grid).encode("utf-8")


def _svg(grid: list[list[int]]) -> str:
    cell_w, cell_h, gap = 34, 48, 3
    rows, cols = len(grid), max(len(r) for r in grid)
    width = cols * (cell_w + gap) + gap
    height = rows * (cell_h + gap) + gap
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img">',
        f'<rect width="{width}" height="{height}" rx="10" fill="#141414"/>',
    ]
    for r, row in enumerate(grid):
        for c, code in enumerate(row):
            x = gap + c * (cell_w + gap)
            y = gap + r * (cell_h + gap)
            fill = SWATCH.get(code, "#1e1e1e")
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" rx="3" '
                f'fill="{fill}"/>'
            )
            # The hinge line down the middle of every flap.
            parts.append(
                f'<line x1="{x}" y1="{y + cell_h / 2}" x2="{x + cell_w}" '
                f'y2="{y + cell_h / 2}" stroke="#000" stroke-opacity="0.35"/>'
            )
            if 0 < code < len(PRINTABLE) and code not in SWATCH:
                char = PRINTABLE[code]
                if char.strip():
                    parts.append(
                        f'<text x="{x + cell_w / 2}" y="{y + cell_h / 2}" '
                        'text-anchor="middle" dominant-baseline="central" '
                        'font-family="ui-monospace,Menlo,Consolas,monospace" '
                        f'font-size="26" fill="#f4f1ea">{_esc(char)}</text>'
                    )
    parts.append("</svg>")
    return "".join(parts)


def _esc(char: str) -> str:
    return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}.get(char, char)
