"""Sources that track live Home Assistant state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import (
    TrackStates,
    TrackTemplate,
    TrackTemplateResult,
    async_track_state_change_event,
    async_track_state_change_filtered,
    async_track_template_result,
)
from homeassistant.helpers.template import Template

from ..core.layout import clean
from ..core.models import TIER_CONTENT, TIER_TASK, Item
from .base import Source

_LOGGER = logging.getLogger(__name__)

ATTR_MESSAGE = "message"
ATTR_TIER = "tier"
ATTR_COLOUR = "colour"


def _as_colour(value: object, default: int | None) -> int | None:
    """A declared colour, or the source's default if it is not usable."""
    try:
        code = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return code if 63 <= code <= 68 else default


class TodoSource(Source):
    """One item per incomplete entry on a to-do list.

    Deliberately reads the list once per change and keeps the result, rather
    than calling ``todo.get_items`` on every tick - the service call is async
    and the scheduler runs synchronously.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        source_id: str,
        name: str,
        entity_id: str,
        tier: str = TIER_TASK,
        colour: int | None = None,
    ) -> None:
        super().__init__(hass, source_id, name)
        self.entity_id = entity_id
        self.tier = tier
        self.colour = colour
        self._cache: list[tuple[str, str]] = []

    async def async_setup(self) -> None:
        await self._refresh()
        self._listeners.append(
            async_track_state_change_event(
                self.hass, [self.entity_id], self._handle_state
            )
        )

    @callback
    def _handle_state(self, _event: Event[EventStateChangedData]) -> None:
        self.hass.async_create_task(self._refresh_and_notify())

    async def _refresh_and_notify(self) -> None:
        await self._refresh()
        self._changed()

    async def _refresh(self) -> None:
        try:
            response = await self.hass.services.async_call(
                "todo",
                "get_items",
                {"entity_id": self.entity_id, "status": "needs_action"},
                blocking=True,
                return_response=True,
            )
        except Exception:  # the list may not be loaded yet
            _LOGGER.debug("could not read %s; treating it as empty", self.entity_id)
            self._cache = []
            return
        entries = (response or {}).get(self.entity_id, {}).get("items", [])
        cleaned = (
            (
                str(entry.get("uid") or entry.get("summary")),
                clean(str(entry.get("summary", "")), markup=False),
            )
            for entry in entries
        )
        self._cache = [(uid, summary) for uid, summary in cleaned if summary]

    def items(self, now: datetime) -> list[Item]:
        return [
            Item(
                id=uid,
                source=self.source_id,
                text=summary,
                tier=self.tier,
                colour=self.colour,
                meta={"source_name": self.name, "entity_id": self.entity_id},
            )
            for uid, summary in self._cache
        ]


class DeclaredSource(Source):
    """Cards declared as entities elsewhere in Home Assistant.

    An entity that is ``on`` and carries a ``message`` attribute becomes an
    item for as long as it stays on. This is the path for people who keep
    their config in YAML packages: the message lives next to the detector that
    raises it, in a file you can diff, and it adds and removes itself with no
    automation involved at all.

    Discovery is by attribute rather than by template, so a newly added card
    is picked up as soon as its entity appears - which is exactly what a
    template sensor could not do.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        source_id: str,
        name: str,
        entity_ids: list[str] | None = None,
        domains: tuple[str, ...] = ("binary_sensor", "input_boolean", "sensor"),
        default_tier: str = TIER_TASK,
        colour: int | None = None,
    ) -> None:
        super().__init__(hass, source_id, name)
        self.entity_ids = entity_ids or []
        self.domains = domains
        self.default_tier = default_tier
        self.colour = colour

    async def async_setup(self) -> None:
        # One filtered listener covers both cases. Watching the domains
        # rather than a snapshot of matching entities is what lets a card
        # added to a package file after startup not just appear, but keep
        # reporting its on/off changes without a reload.
        watch = (
            TrackStates(False, set(self.entity_ids), set())
            if self.entity_ids
            else TrackStates(False, set(), set(self.domains))
        )
        tracker = async_track_state_change_filtered(self.hass, watch, self._on_state)
        self._listeners.append(tracker.async_remove)

    @callback
    def _on_state(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if any(s is not None and ATTR_MESSAGE in s.attributes for s in (old, new)):
            self._changed()

    def _candidates(self) -> list[str]:
        if self.entity_ids:
            return self.entity_ids
        return [
            state.entity_id
            for domain in self.domains
            for state in self.hass.states.async_all(domain)
            if ATTR_MESSAGE in state.attributes
        ]

    def items(self, now: datetime) -> list[Item]:
        out: list[Item] = []
        for entity_id in self._candidates():
            state = self.hass.states.get(entity_id)
            if state is None or state.state != "on":
                continue
            message = state.attributes.get(ATTR_MESSAGE)
            if not message:
                continue
            out.append(
                Item(
                    id=entity_id,
                    source=self.source_id,
                    text=str(message),
                    tier=str(state.attributes.get(ATTR_TIER, self.default_tier)),
                    colour=_as_colour(state.attributes.get(ATTR_COLOUR), self.colour),
                    meta={"source_name": self.name, "entity_id": entity_id},
                )
            )
        return out


class ServiceSource(Source):
    """Items pushed in by ``vestassistant.add_item``.

    Two guards exist because the removal half of an imperative API is the half
    that gets missed: ``ttl`` ages an item out, and ``expire_when`` is a
    template the integration tracks, so removal becomes a state rather than
    an event somebody has to remember to fire.
    """

    def __init__(self, hass: HomeAssistant, source_id: str = "service") -> None:
        super().__init__(hass, source_id, "Service")
        self._items: dict[str, dict[str, Any]] = {}
        self._templates: dict[str, Template] = {}
        self._trackers: dict[str, Callable[[], None]] = {}

    # -- persistence ------------------------------------------------------

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return self._items

    def restore(self, data: dict[str, dict[str, Any]] | None) -> None:
        self._items = dict(data or {})

    # -- lifecycle --------------------------------------------------------

    async def async_setup(self) -> None:
        for item_id, raw in self._items.items():
            self._track(item_id, raw.get("expire_when"))

    async def async_unload(self) -> None:
        for item_id in list(self._trackers):
            self._untrack(item_id)
        await super().async_unload()

    # -- mutation ---------------------------------------------------------

    def add(
        self,
        item_id: str,
        text: str,
        tier: str = TIER_CONTENT,
        *,
        now: datetime,
        ttl: timedelta | None = None,
        expire_when: str | None = None,
        dwell: timedelta | None = None,
        colour: int | None = None,
    ) -> None:
        # Idempotent on id: calling add twice updates rather than duplicating,
        # which is the de-duplication every caller would otherwise hand-roll.
        self._items[item_id] = {
            "text": text,
            "tier": tier,
            "colour": colour,
            "expires": (now + ttl).isoformat() if ttl else None,
            "expire_when": expire_when,
            "dwell": dwell.total_seconds() if dwell else None,
        }
        self._track(item_id, expire_when)
        self._changed()

    def remove(self, item_id: str) -> bool:
        existed = self._items.pop(item_id, None) is not None
        if existed:
            self._untrack(item_id)
            self._changed()
        return existed

    # -- expire_when tracking ---------------------------------------------

    def _track(self, item_id: str, expire_when: str | None) -> None:
        """Watch the item's template so it can leave without a tick from elsewhere."""
        self._untrack(item_id)
        if not expire_when:
            return
        template = Template(expire_when, self.hass)
        self._templates[item_id] = template
        info = async_track_template_result(
            self.hass, [TrackTemplate(template, None)], self._on_template
        )
        self._trackers[item_id] = info.async_remove

    def _untrack(self, item_id: str) -> None:
        self._templates.pop(item_id, None)
        if unsub := self._trackers.pop(item_id, None):
            unsub()

    @callback
    def _on_template(
        self, _event: Event | None, _updates: list[TrackTemplateResult]
    ) -> None:
        self._changed()

    def _satisfied(self, item_id: str) -> bool:
        template = self._templates.get(item_id)
        if template is None:
            return False
        try:
            return bool(template.async_render(parse_result=True))
        except Exception:  # a broken template keeps the item
            return False

    # -- Source protocol --------------------------------------------------

    def items(self, now: datetime) -> list[Item]:
        out: list[Item] = []
        satisfied: list[str] = []
        for item_id, raw in self._items.items():
            if self._satisfied(item_id):
                satisfied.append(item_id)
                continue
            # Items stored before multi-card was removed kept a list; take
            # the first rather than failing to restore them at all.
            text = raw.get("text") or (raw.get("cards") or [""])[0]
            if not text:
                continue
            out.append(
                Item(
                    id=item_id,
                    source=self.source_id,
                    text=text,
                    tier=raw.get("tier", TIER_CONTENT),
                    colour=raw.get("colour"),
                    expires=_parse(raw.get("expires")),
                    dwell=(
                        timedelta(seconds=raw["dwell"]) if raw.get("dwell") else None
                    ),
                    meta={"source_name": self.name},
                )
            )
        for item_id in satisfied:
            self._items.pop(item_id, None)
            self._untrack(item_id)
        return out


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
