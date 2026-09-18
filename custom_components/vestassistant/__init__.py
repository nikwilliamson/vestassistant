"""Vestassistant - a message scheduler for Vestaboard.

Not affiliated with or endorsed by Vestaboard.
"""

from __future__ import annotations

from datetime import time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import (
    ATTR_CARDS,
    ATTR_COLOUR,
    ATTR_DURATION,
    ATTR_EXPIRE_WHEN,
    ATTR_ITEM_ID,
    ATTR_MESSAGE,
    ATTR_TIER,
    ATTR_TTL,
    CONF_API_KEY,
    CONF_BLEND,
    CONF_CLOCK,
    CONF_CLOCK_REFRESH,
    CONF_COLOUR,
    CONF_DWELL,
    CONF_ENTITY_ID,
    CONF_ENTRIES,
    CONF_FORECAST,
    CONF_FORECAST_ENTITY,
    CONF_HOST,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SOURCE_TYPE,
    CONF_SUMMARY_TEMPLATE,
    CONF_SUMMARY_THRESHOLD,
    CONF_TIER,
    CONF_TOKEN,
    CONF_TRANSPORT,
    DEFAULT_BLEND,
    DEFAULT_CLOCK_REFRESH,
    DEFAULT_DWELL_MINUTES,
    DEFAULT_SUMMARY_TEMPLATE,
    DEFAULT_SUMMARY_THRESHOLD,
    DOMAIN,
    SERVICE_ADD_ITEM,
    SERVICE_NEXT,
    SERVICE_PIN,
    SERVICE_REMOVE_ITEM,
    SERVICE_VALIDATE,
    SOURCE_DECLARED,
    SOURCE_LIST,
    SOURCE_TODO,
    TRANSPORT_CLOUD,
)
from .coordinator import VestassistantConfigEntry, VestassistantCoordinator
from .core.layout import NOTE, Geometry, fit
from .core.models import (
    TIER_CONTENT,
    Item,
    SchedulerConfig,
    TierSet,
    Trigger,
    resolve_band,
)
from .sources.base import ListSource
from .sources.dynamic import DeclaredSource, ServiceSource, TodoSource
from .sources.generated import ClockSource, ForecastSource
from .transport.base import VestaboardAuthError, VestaboardError
from .transport.cloud import CloudTransport
from .transport.local import LocalTransport

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.IMAGE,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.TIME,
]


def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    parsed = dt_util.parse_time(value)
    return parsed


def _scheduler_config(entry: ConfigEntry) -> SchedulerConfig:
    options = entry.options
    return SchedulerConfig(
        dwell=timedelta(minutes=options.get(CONF_DWELL, DEFAULT_DWELL_MINUTES)),
        summary_threshold=options.get(
            CONF_SUMMARY_THRESHOLD, DEFAULT_SUMMARY_THRESHOLD
        ),
        summary_template=options.get(CONF_SUMMARY_TEMPLATE, DEFAULT_SUMMARY_TEMPLATE),
        quiet_start=_parse_time(options.get(CONF_QUIET_START)),
        quiet_end=_parse_time(options.get(CONF_QUIET_END)),
        tiers=TierSet(),
        blend=options.get(CONF_BLEND, DEFAULT_BLEND),
    )


def _build_transport(hass: HomeAssistant, entry: ConfigEntry):
    session = async_get_clientsession(hass)
    if entry.data.get(CONF_TRANSPORT) == TRANSPORT_CLOUD:
        return CloudTransport(session, entry.data[CONF_TOKEN])
    return LocalTransport(session, entry.data[CONF_HOST], entry.data[CONF_API_KEY])


async def async_setup_entry(
    hass: HomeAssistant, entry: VestassistantConfigEntry
) -> bool:
    """Set up one board."""
    transport = _build_transport(hass, entry)
    coordinator = VestassistantCoordinator(
        hass, entry, transport, _scheduler_config(entry)
    )

    # The service source is always present; the built-in cards come from the
    # entry's options, and everything else from subentries.
    coordinator.register_source(ServiceSource(hass))
    for source in _generated_sources(hass, entry):
        coordinator.register_source(source)
    for subentry in entry.subentries.values():
        source = _source_from_subentry(hass, subentry)
        if source is not None:
            coordinator.register_source(source)

    try:
        await coordinator.async_prepare()
    except VestaboardAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except VestaboardError as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_tick(Trigger.START)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    _async_register_services(hass)
    return True


def _generated_sources(hass: HomeAssistant, entry: ConfigEntry) -> list:
    """The clock and forecast cards, if their switches are on.

    Built from options rather than subentries so that turning one off leaves
    its settings behind, ready for when it goes back on.
    """
    options = entry.options
    out: list = []
    if options.get(CONF_CLOCK):
        minutes = options.get(CONF_CLOCK_REFRESH, DEFAULT_CLOCK_REFRESH)
        out.append(ClockSource(hass, refresh=timedelta(minutes=int(minutes))))
    # An entity is required rather than assumed: there is no sensible default
    # weather entity, and guessing one would put somebody else's city on the
    # wall.
    if options.get(CONF_FORECAST) and (entity := options.get(CONF_FORECAST_ENTITY)):
        out.append(ForecastSource(hass, entity_id=entity))
    return out


def _source_from_subentry(hass: HomeAssistant, subentry) -> object | None:
    data = subentry.data
    kind = data.get(CONF_SOURCE_TYPE)
    title = subentry.title or kind or "source"
    tier = data.get(CONF_TIER, TIER_CONTENT)
    colour = data.get(CONF_COLOUR)
    colour = int(colour) if colour is not None else None
    if kind == SOURCE_LIST:
        entries = [
            [part.strip() for part in str(line).split("|")]
            for line in data.get(CONF_ENTRIES, [])
            if str(line).strip()
        ]
        return ListSource(hass, subentry.subentry_id, title, entries, tier, colour)
    if kind == SOURCE_TODO:
        return TodoSource(
            hass, subentry.subentry_id, title, data[CONF_ENTITY_ID], tier, colour
        )
    if kind == SOURCE_DECLARED:
        return DeclaredSource(
            hass,
            subentry.subentry_id,
            title,
            entity_ids=data.get(CONF_ENTITY_ID) or None,
            default_tier=tier,
            colour=colour,
        )
    return None


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: VestassistantConfigEntry
) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


# ----------------------------------------------------------------------
# services
# ----------------------------------------------------------------------

ADD_ITEM_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ITEM_ID): cv.string,
        vol.Exclusive(ATTR_MESSAGE, "content"): cv.string,
        vol.Exclusive(ATTR_CARDS, "content"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_TIER, default=TIER_CONTENT): cv.string,
        vol.Optional(ATTR_COLOUR): vol.All(
            vol.Coerce(int), vol.Range(min=63, max=68)
        ),
        vol.Optional(ATTR_TTL): cv.time_period,
        vol.Optional(ATTR_EXPIRE_WHEN): cv.template,
        vol.Optional("entry_id"): cv.string,
    }
)

REMOVE_ITEM_SCHEMA = vol.Schema(
    {vol.Required(ATTR_ITEM_ID): cv.string, vol.Optional("entry_id"): cv.string}
)

PIN_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_DURATION, default={"minutes": 10}): cv.time_period,
        vol.Optional("entry_id"): cv.string,
    }
)

VALIDATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional("rows"): cv.positive_int,
        vol.Optional("columns"): cv.positive_int,
        vol.Optional(ATTR_TIER): cv.string,
        vol.Optional(ATTR_COLOUR): vol.All(
            vol.Coerce(int), vol.Range(min=63, max=68)
        ),
        vol.Optional("entry_id"): cv.string,
    }
)


def _coordinators(
    hass: HomeAssistant, call: ServiceCall
) -> list[VestassistantCoordinator]:
    entry_id = call.data.get("entry_id")
    entries = hass.config_entries.async_entries(DOMAIN)
    out = []
    for entry in entries:
        if entry_id and entry.entry_id != entry_id:
            continue
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is not None:
            out.append(coordinator)
    return out


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_ADD_ITEM):
        return

    async def _add_item(call: ServiceCall) -> None:
        cards = call.data.get(ATTR_CARDS) or [call.data[ATTR_MESSAGE]]
        expire = call.data.get(ATTR_EXPIRE_WHEN)
        for coordinator in _coordinators(hass, call):
            source = coordinator._service_source
            if source is None:
                continue
            source.add(
                call.data[ATTR_ITEM_ID],
                cards,
                call.data.get(ATTR_TIER, TIER_CONTENT),
                now=dt_util.now(),
                ttl=call.data.get(ATTR_TTL),
                expire_when=expire.template if expire else None,
                colour=call.data.get(ATTR_COLOUR),
            )
            await coordinator.async_tick(Trigger.ITEMS_CHANGED)

    async def _remove_item(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass, call):
            source = coordinator._service_source
            if source is not None and source.remove(call.data[ATTR_ITEM_ID]):
                await coordinator.async_tick(Trigger.ITEMS_CHANGED)

    async def _next(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass, call):
            await coordinator.async_next()

    async def _pin(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass, call):
            await coordinator.async_pin(
                call.data[ATTR_MESSAGE], call.data[ATTR_DURATION]
            )

    async def _validate(call: ServiceCall) -> ServiceResponse:
        """Check a message against the board's geometry.

        Exposed as a service with a response so that content can be checked
        while it is being written, rather than discovered garbled on the wall.
        """
        coordinators = _coordinators(hass, call)
        geometry: Geometry
        if "rows" in call.data and "columns" in call.data:
            geometry = Geometry(rows=call.data["rows"], cols=call.data["columns"])
        elif coordinators and coordinators[0].geometry:
            geometry = coordinators[0].geometry
        else:
            geometry = NOTE
        band = None
        if ATTR_TIER in call.data:
            tiers = (
                coordinators[0].scheduler_config.tiers if coordinators else TierSet()
            )
            band = resolve_band(
                Item(
                    id="validate",
                    source="validate",
                    cards=("",),
                    tier=call.data[ATTR_TIER],
                    colour=call.data.get(ATTR_COLOUR),
                ),
                tiers,
            )
        result = fit(call.data[ATTR_MESSAGE], geometry, shorten=True, band=band)
        return {
            "fits": result.fits,
            "error": result.error,
            "rows_needed": result.rows_needed,
            "rows_available": geometry.rows,
            "columns": geometry.cols,
            "board": geometry.name,
            "preview": result.preview,
            "overflow": result.overflow,
            "shortened": result.shortened,
        }

    hass.services.async_register(DOMAIN, SERVICE_ADD_ITEM, _add_item, ADD_ITEM_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_ITEM, _remove_item, REMOVE_ITEM_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_NEXT, _next)
    hass.services.async_register(DOMAIN, SERVICE_PIN, _pin, PIN_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_VALIDATE,
        _validate,
        VALIDATE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
