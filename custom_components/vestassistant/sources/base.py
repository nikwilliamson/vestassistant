"""Source interface and the static list source.

A source yields zero or more Items. That is the whole contract - which is what
lets a hand-typed list, a to-do list, an entity condition and a service call
all feed the same rotation without the scheduler knowing the difference. A
generator that computes its items rather than storing them plugs in here too,
with no changes above this line.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from datetime import datetime

from homeassistant.core import CALLBACK_TYPE, HomeAssistant

from ..core.models import TIER_CONTENT, Item


class Source(abc.ABC):
    """Something that contributes items to the board."""

    #: Stable identifier, unique per config subentry. Forms half of an item's
    #: key, so changing it resets that source's cursor.
    source_id: str

    #: Human-readable, for diagnostics and the current-item attributes.
    name: str

    def __init__(self, hass: HomeAssistant, source_id: str, name: str) -> None:
        self.hass = hass
        self.source_id = source_id
        self.name = name
        self._listeners: list[CALLBACK_TYPE] = []
        self._notify: Callable[[], None] | None = None

    def set_notifier(self, notify: Callable[[], None]) -> None:
        """Register the callback used to tell the coordinator to re-evaluate."""
        self._notify = notify

    def _changed(self, *_: object) -> None:
        if self._notify is not None:
            self._notify()

    async def async_setup(self) -> None:  # noqa: B027 - optional hook
        """Subscribe to whatever this source needs to watch.

        Deliberately concrete and empty: a static source has nothing to watch.
        """

    async def async_unload(self) -> None:
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()

    @abc.abstractmethod
    def items(self, now: datetime) -> list[Item]:
        """Return the items currently contributed by this source."""


class ListSource(Source):
    """A list of messages typed into the integration's configuration.

    Each entry is a list of cards rather than a bare string, even though most
    entries will have exactly one. A joke's setup and punchline are two cards
    of one item, and making that the shape from the start avoids migrating
    everybody's config the first time someone wants one.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        source_id: str,
        name: str,
        entries: list[list[str]],
        tier: str = TIER_CONTENT,
    ) -> None:
        super().__init__(hass, source_id, name)
        self.tier = tier
        self.entries = entries

    def items(self, now: datetime) -> list[Item]:
        out: list[Item] = []
        for index, cards in enumerate(self.entries):
            cards = [c for c in cards if c and c.strip()]
            if not cards:
                continue
            out.append(
                Item(
                    id=str(index),
                    source=self.source_id,
                    cards=tuple(cards),
                    tier=self.tier,
                    meta={"source_name": self.name},
                )
            )
        # Order is config order, and the scheduler's sort is stable, so the
        # rotation runs in the order the messages were written.
        return out
