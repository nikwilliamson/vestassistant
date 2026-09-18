"""Config and options flows.

Step one is the choice the two transports force: a board on the LAN with an
enablement token, or a cloud token that works anywhere. Everything after that
is identical, because the geometry is read off the board rather than asked
for.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .const import (
    BOARD_BLACK,
    BOARD_WHITE,
    CONF_API_KEY,
    CONF_BLEND,
    CONF_BOARD_COLOUR,
    CONF_CLOCK,
    CONF_CLOCK_REFRESH,
    CONF_COLOUR,
    CONF_DWELL,
    CONF_ENABLEMENT_TOKEN,
    CONF_ENTITY_ID,
    CONF_ENTRIES,
    CONF_FORECAST,
    CONF_FORECAST_ENTITY,
    CONF_HOST,
    CONF_HUES,
    CONF_PATTERNS,
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
    SOURCE_DECLARED,
    SOURCE_LIST,
    SOURCE_PATTERN,
    SOURCE_TODO,
    SUBENTRY_SOURCE,
    TRANSPORT_CLOUD,
    TRANSPORT_LOCAL,
)
from .coordinator import VestassistantCoordinator
from .core.layout import NOTE, Geometry, fit
from .core.models import TIER_CONTENT, TIER_CRITICAL, TIER_TASK, TierSet, resolve_band
from .core.patterns import CONTRAST, HUES, PATTERNS
from .transport.base import Transport, VestaboardAuthError, VestaboardError
from .transport.cloud import CloudTransport
from .transport.local import LocalTransport

TIER_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[TIER_CRITICAL, TIER_TASK, TIER_CONTENT],
        translation_key="tier",
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)

#: Only the six hues that behave identically on both transports and both
#: models. 71 is unavailable on the local API and 69 and 70 invert with the
#: board's physical colour, which neither API reports.
COLOUR_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=["63", "64", "65", "66", "67", "68"],
        translation_key="colour",
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)

PATTERN_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=list(PATTERNS),
        translation_key="pattern",
        mode=selector.SelectSelectorMode.LIST,
        multiple=True,
    )
)

HUES_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[*(str(h) for h in HUES), CONTRAST],
        translation_key="hue",
        mode=selector.SelectSelectorMode.LIST,
        multiple=True,
    )
)

BOARD_COLOUR_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[BOARD_BLACK, BOARD_WHITE],
        translation_key="board_colour",
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)


class VestassistantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a board."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if user_input[CONF_TRANSPORT] == TRANSPORT_LOCAL:
                return await self.async_step_local()
            return await self.async_step_cloud()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TRANSPORT, default=TRANSPORT_LOCAL): (
                        selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[TRANSPORT_LOCAL, TRANSPORT_CLOUD],
                                translation_key="transport",
                                mode=selector.SelectSelectorMode.LIST,
                            )
                        )
                    )
                }
            ),
        )

    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            api_key = user_input.get(CONF_API_KEY)
            token = user_input.get(CONF_ENABLEMENT_TOKEN)
            if not api_key and not token:
                errors["base"] = "missing_credentials"
            try:
                if not errors and not api_key:
                    api_key = await LocalTransport.async_enable(
                        session, user_input[CONF_HOST], token
                    )
                if not errors:
                    transport = LocalTransport(session, user_input[CONF_HOST], api_key)
                    geometry = await transport.async_detect_geometry()
            except VestaboardAuthError:
                errors["base"] = "invalid_auth"
            except VestaboardError:
                errors["base"] = "cannot_connect"
            if not errors:
                await self.async_set_unique_id(f"local:{user_input[CONF_HOST]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=geometry.name,
                    data={
                        CONF_TRANSPORT: TRANSPORT_LOCAL,
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_API_KEY: api_key,
                    },
                    options=_default_options(),
                )

        return self.async_show_form(
            step_id="local",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default="vestaboard.local"): str,
                    vol.Optional(CONF_ENABLEMENT_TOKEN): str,
                    vol.Optional(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            transport = CloudTransport(session, user_input[CONF_TOKEN])
            try:
                geometry = await transport.async_detect_geometry()
            except VestaboardAuthError:
                errors["base"] = "invalid_auth"
            except VestaboardError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"cloud:{user_input[CONF_TOKEN][:8]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=geometry.name,
                    data={
                        CONF_TRANSPORT: TRANSPORT_CLOUD,
                        CONF_TOKEN: user_input[CONF_TOKEN],
                    },
                    options=_default_options(),
                )

        return self.async_show_form(
            step_id="cloud",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        cloud = entry.data.get(CONF_TRANSPORT) == TRANSPORT_CLOUD
        key = CONF_TOKEN if cloud else CONF_API_KEY
        errors: dict[str, str] = {}
        if user_input is not None:
            # Prove the new credential works before it replaces the old one,
            # exactly as the create path does.
            session = async_get_clientsession(self.hass)
            transport: Transport = (
                CloudTransport(session, user_input[key])
                if cloud
                else LocalTransport(session, entry.data[CONF_HOST], user_input[key])
            )
            try:
                await transport.async_detect_geometry()
            except VestaboardAuthError:
                errors["base"] = "invalid_auth"
            except VestaboardError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(key): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return VestassistantOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_SOURCE: SourceSubentryFlow}


def _default_options() -> dict[str, Any]:
    return {
        CONF_DWELL: DEFAULT_DWELL_MINUTES,
        CONF_SUMMARY_THRESHOLD: DEFAULT_SUMMARY_THRESHOLD,
        CONF_SUMMARY_TEMPLATE: DEFAULT_SUMMARY_TEMPLATE,
        CONF_BLEND: DEFAULT_BLEND,
        CONF_CLOCK: False,
        CONF_CLOCK_REFRESH: DEFAULT_CLOCK_REFRESH,
        CONF_FORECAST: False,
        CONF_BOARD_COLOUR: BOARD_BLACK,
    }


class VestassistantOptionsFlow(OptionsFlow):
    """Dwell, quiet hours, summary, blend, and the built-in cards."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The settings that have no sensible entity.

        Dwell, the summary threshold, quiet hours, the clock and the forecast
        all have their own entities, so they are not repeated here - they
        live in the same options dict and would otherwise be two controls for
        one value. What is left is a free-text template, a choice of
        strategy, an entity picker, and the board's colour - which neither
        API reports, and which decides whether white or black tiles show.
        """
        if user_input is not None:
            # Merge rather than replace: the entities write into these same
            # options, and returning only this form's fields would wipe them.
            # Read with .get so clearing the weather entity actually clears it.
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    CONF_SUMMARY_TEMPLATE: user_input[CONF_SUMMARY_TEMPLATE],
                    CONF_BLEND: user_input[CONF_BLEND],
                    CONF_BOARD_COLOUR: user_input[CONF_BOARD_COLOUR],
                    CONF_FORECAST_ENTITY: user_input.get(CONF_FORECAST_ENTITY),
                }
            )

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SUMMARY_TEMPLATE,
                        default=options.get(
                            CONF_SUMMARY_TEMPLATE, DEFAULT_SUMMARY_TEMPLATE
                        ),
                    ): str,
                    vol.Required(
                        CONF_BLEND, default=options.get(CONF_BLEND, DEFAULT_BLEND)
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["alternate", "attention_first"],
                            translation_key="blend",
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_BOARD_COLOUR,
                        default=options.get(CONF_BOARD_COLOUR, BOARD_BLACK),
                    ): BOARD_COLOUR_SELECTOR,
                    vol.Optional(
                        CONF_FORECAST_ENTITY,
                        description={
                            "suggested_value": options.get(CONF_FORECAST_ENTITY)
                        },
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="weather")
                    ),
                }
            ),
        )


class SourceSubentryFlow(ConfigSubentryFlow):
    """Add or edit a source.

    The same three forms serve both: creating one starts at ``user`` to pick
    a kind, editing one jumps straight to the form for the kind it already
    is. Without the edit path a message list was add-or-delete, so fixing a
    typo meant retyping every message in it.
    """

    _reconfiguring = False

    # -- shared plumbing --------------------------------------------------

    def _current(self) -> dict[str, Any]:
        """The values to prefill, empty when creating."""
        if not self._reconfiguring:
            return {}
        return dict(self._get_reconfigure_subentry().data)

    def _name(self, fallback: str) -> str:
        if not self._reconfiguring:
            return fallback
        return self._get_reconfigure_subentry().title or fallback

    def _save(self, title: str, data: dict[str, Any]) -> SubentryFlowResult:
        if self._reconfiguring:
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=data,
                title=title,
            )
        return self.async_create_entry(title=title, data=data)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        self._reconfiguring = True
        kind = self._get_reconfigure_subentry().data.get(CONF_SOURCE_TYPE)
        if kind == SOURCE_TODO:
            return await self.async_step_todo()
        if kind == SOURCE_DECLARED:
            return await self.async_step_declared()
        if kind == SOURCE_PATTERN:
            return await self.async_step_pattern()
        return await self.async_step_list()

    # -- picking a kind ---------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if user_input is not None:
            kind = user_input[CONF_SOURCE_TYPE]
            if kind == SOURCE_LIST:
                return await self.async_step_list()
            if kind == SOURCE_TODO:
                return await self.async_step_todo()
            if kind == SOURCE_PATTERN:
                return await self.async_step_pattern()
            return await self.async_step_declared()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCE_TYPE, default=SOURCE_LIST): (
                        selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    SOURCE_LIST,
                                    SOURCE_TODO,
                                    SOURCE_DECLARED,
                                    SOURCE_PATTERN,
                                ],
                                translation_key="source_type",
                                mode=selector.SelectSelectorMode.LIST,
                            )
                        )
                    )
                }
            ),
        )

    # -- the three kinds --------------------------------------------------

    async def async_step_list(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        current = self._current()
        if user_input is not None:
            entries = [
                line.strip()
                for line in user_input.get(CONF_ENTRIES, [])
                if line and line.strip()
            ]
            # Checked here rather than at render time: finding out a message
            # does not fit because it is garbled on the wall is the bad
            # version of this feedback loop. The rendered message carries a
            # band, so validation has to reserve the same space or a message
            # can pass here and still get shortened on the wall.
            # The selector hands back a string ("66"); Band wants an int.
            raw_colour = user_input.get(CONF_COLOUR)
            colour = int(raw_colour) if raw_colour is not None else None
            band = resolve_band(user_input[CONF_TIER], colour, self._tiers())
            # Without shorten: the rendered card may abbreviate, but a message
            # that only fits abbreviated is worth telling the author about
            # while they can still reword it.
            results = [fit(line, self._geometry(), band=band) for line in entries]
            if any(r.error for r in results):
                errors[CONF_ENTRIES] = "invalid_character"
            elif any(not r.fits for r in results):
                errors[CONF_ENTRIES] = "does_not_fit"
            else:
                return self._save(
                    user_input["name"],
                    {
                        CONF_SOURCE_TYPE: SOURCE_LIST,
                        CONF_ENTRIES: entries,
                        CONF_TIER: user_input[CONF_TIER],
                        CONF_COLOUR: user_input.get(CONF_COLOUR),
                    },
                )

        return self.async_show_form(
            step_id="list",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=self._name("Typed messages")): str,
                    vol.Required(
                        CONF_TIER, default=current.get(CONF_TIER, TIER_CONTENT)
                    ): TIER_SELECTOR,
                    vol.Optional(
                        CONF_COLOUR,
                        description={"suggested_value": current.get(CONF_COLOUR)},
                    ): COLOUR_SELECTOR,
                    vol.Required(
                        CONF_ENTRIES, default=current.get(CONF_ENTRIES, [])
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True, multiple=True)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={"board": self._geometry().name},
        )

    async def async_step_todo(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        current = self._current()
        if user_input is not None:
            return self._save(
                user_input["name"],
                {
                    CONF_SOURCE_TYPE: SOURCE_TODO,
                    CONF_ENTITY_ID: user_input[CONF_ENTITY_ID],
                    CONF_TIER: user_input[CONF_TIER],
                    CONF_COLOUR: user_input.get(CONF_COLOUR),
                },
            )
        return self.async_show_form(
            step_id="todo",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=self._name("To-do")): str,
                    vol.Required(
                        CONF_ENTITY_ID,
                        description={"suggested_value": current.get(CONF_ENTITY_ID)},
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="todo")
                    ),
                    vol.Required(
                        CONF_TIER, default=current.get(CONF_TIER, TIER_TASK)
                    ): TIER_SELECTOR,
                    vol.Optional(
                        CONF_COLOUR,
                        description={"suggested_value": current.get(CONF_COLOUR)},
                    ): COLOUR_SELECTOR,
                }
            ),
        )

    async def async_step_declared(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        current = self._current()
        if user_input is not None:
            return self._save(
                user_input["name"],
                {
                    CONF_SOURCE_TYPE: SOURCE_DECLARED,
                    CONF_ENTITY_ID: user_input.get(CONF_ENTITY_ID) or [],
                    CONF_TIER: user_input[CONF_TIER],
                    CONF_COLOUR: user_input.get(CONF_COLOUR),
                },
            )
        return self.async_show_form(
            step_id="declared",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=self._name("Entity messages")): str,
                    vol.Optional(
                        CONF_ENTITY_ID,
                        description={
                            "suggested_value": current.get(CONF_ENTITY_ID) or None
                        },
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["binary_sensor", "input_boolean", "sensor"],
                            multiple=True,
                        )
                    ),
                    vol.Required(
                        CONF_TIER, default=current.get(CONF_TIER, TIER_TASK)
                    ): TIER_SELECTOR,
                    vol.Optional(
                        CONF_COLOUR,
                        description={"suggested_value": current.get(CONF_COLOUR)},
                    ): COLOUR_SELECTOR,
                }
            ),
        )

    async def async_step_pattern(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        current = self._current()
        if user_input is not None:
            patterns = user_input.get(CONF_PATTERNS) or []
            if not patterns:
                errors[CONF_PATTERNS] = "no_patterns"
            else:
                return self._save(
                    user_input["name"],
                    {
                        CONF_SOURCE_TYPE: SOURCE_PATTERN,
                        CONF_PATTERNS: patterns,
                        CONF_HUES: user_input.get(CONF_HUES) or [],
                    },
                )
        return self.async_show_form(
            step_id="pattern",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=self._name("Colour")): str,
                    vol.Required(
                        CONF_PATTERNS,
                        default=current.get(CONF_PATTERNS, list(PATTERNS)),
                    ): PATTERN_SELECTOR,
                    vol.Optional(
                        CONF_HUES,
                        description={"suggested_value": current.get(CONF_HUES)},
                    ): HUES_SELECTOR,
                }
            ),
            errors=errors,
        )

    def _coordinator(self) -> VestassistantCoordinator | None:
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return None
        return entry.runtime_data

    def _geometry(self) -> Geometry:
        coordinator = self._coordinator()
        if coordinator is not None and coordinator.geometry is not None:
            return coordinator.geometry
        return NOTE

    def _tiers(self) -> TierSet:
        coordinator = self._coordinator()
        if coordinator is not None:
            return coordinator.scheduler_config.tiers
        return TierSet()
