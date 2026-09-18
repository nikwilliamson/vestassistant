"""Sources that track live Home Assistant state."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_added_domain,
    async_track_state_change_event,
)
from homeassistant.helpers.template import Template

from ..core.models import TIER_CONTENT, TIER_TASK, Item
from .base import Source

ATTR_MESSAGE = "message"
ATTR_TIER = "tier"
ATTR_CARDS = "cards"
ATTR_TTL = "ttl"


class TodoSource(Source):
    """One item per incomplete entry on a to-do list.

    Deliberately reads the entity's own state for the count and its cached
    items for the text, rather than calling ``todo.get_items`` on every tick -
    the service call is async and the scheduler runs synchronously.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        source_id: str,
        name: str,
        entity_id: str,
        tier: str = TIER_TASK,
    ) -> None:
        super().__init__(hass, source_id, name)
        self.entity_id = entity_id
        self.tier = tier
        self._cache: list[tuple[str, str]] = []

    async def async_setup(self) -> None:
        await self._refresh()
        self._listeners.append(
            async_track_state_change_event(
                self.hass, [self.entity_id], self._handle_state
            )
        )

    @callback
    def _handle_state(self, event) -> None:
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
        except Exception:
            self._cache = []
            return
        entries = (response or {}).get(self.entity_id, {}).get("items", [])
        self._cache = [
            (
                str(entry.get("uid") or entry.get("summary")),
                str(entry.get("summary", "")),
            )
            for entry in entries
            if entry.get("summary")
        ]

    def items(self, now: datetime) -> list[Item]:
        return [
            Item(
                id=uid,
                source=self.source_id,
                cards=(summary,),
                tier=self.tier,
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
    ) -> None:
        super().__init__(hass, source_id, name)
        self.entity_ids = entity_ids or []
        self.domains = domains
        self.default_tier = default_tier

    async def async_setup(self) -> None:
        if self.entity_ids:
            self._listeners.append(
                async_track_state_change_event(
                    self.hass, self.entity_ids, self._changed
                )
            )
            return
        # Watching whole domains costs one listener each and means a card
        # added to a package file shows up without a restart.
        for domain in self.domains:
            self._listeners.append(
                async_track_state_added_domain(self.hass, domain, self._changed)
            )
        self._listeners.append(
            async_track_state_change_event(self.hass, self._candidates(), self._changed)
        )

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
            cards = state.attributes.get(ATTR_CARDS)
            if not cards:
                message = state.attributes.get(ATTR_MESSAGE)
                if not message:
                    continue
                cards = [message]
            out.append(
                Item(
                    id=entity_id,
                    source=self.source_id,
                    cards=tuple(str(c) for c in cards),
                    tier=str(state.attributes.get(ATTR_TIER, self.default_tier)),
                    meta={"source_name": self.name, "entity_id": entity_id},
                )
            )
        return out


class ServiceSource(Source):
    """Items pushed in by ``vestassistant.add_item``.

    Two guards exist because the removal half of an imperative API is the half
    that gets missed: ``ttl`` ages an item out, and ``expire_when`` is a
    template the integration evaluates continuously, so removal becomes a
    state rather than an event somebody has to remember to fire.
    """

    def __init__(self, hass: HomeAssistant, source_id: str = "service") -> None:
        super().__init__(hass, source_id, "Service")
        self._items: dict[str, dict] = {}

    # -- persistence ------------------------------------------------------

    def as_dict(self) -> dict[str, dict]:
        return self._items

    def restore(self, data: dict[str, dict] | None) -> None:
        self._items = dict(data or {})

    # -- mutation ---------------------------------------------------------

    def add(
        self,
        item_id: str,
        cards: list[str],
        tier: str = TIER_CONTENT,
        *,
        now: datetime,
        ttl: timedelta | None = None,
        expire_when: str | None = None,
        dwell: timedelta | None = None,
    ) -> None:
        # Idempotent on id: calling add twice updates rather than duplicating,
        # which is the de-duplication every caller would otherwise hand-roll.
        self._items[item_id] = {
            "cards": list(cards),
            "tier": tier,
            "created": now.isoformat(),
            "expires": (now + ttl).isoformat() if ttl else None,
            "expire_when": expire_when,
            "dwell": dwell.total_seconds() if dwell else None,
        }
        self._changed()

    def remove(self, item_id: str) -> bool:
        existed = self._items.pop(item_id, None) is not None
        if existed:
            self._changed()
        return existed

    def clear(self) -> None:
        if self._items:
            self._items.clear()
            self._changed()

    # -- Source protocol --------------------------------------------------

    def items(self, now: datetime) -> list[Item]:
        out: list[Item] = []
        satisfied: list[str] = []
        for item_id, raw in self._items.items():
            expire_when = raw.get("expire_when")
            if expire_when and self._render_bool(expire_when):
                satisfied.append(item_id)
                continue
            expires = raw.get("expires")
            out.append(
                Item(
                    id=item_id,
                    source=self.source_id,
                    cards=tuple(raw["cards"]),
                    tier=raw.get("tier", TIER_CONTENT),
                    created=_parse(raw.get("created")),
                    expires=_parse(expires),
                    dwell=(
                        timedelta(seconds=raw["dwell"]) if raw.get("dwell") else None
                    ),
                    meta={"source_name": self.name},
                )
            )
        for item_id in satisfied:
            self._items.pop(item_id, None)
        return out

    def _render_bool(self, template_str: str) -> bool:
        try:
            template = Template(template_str, self.hass)
            return bool(template.async_render(parse_result=True))
        except Exception:
            return False


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
