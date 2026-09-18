"""Config and options flows.

Step one is the choice the two transports force: a board on the LAN with an
enablement token, or a cloud token that works anywhere. Everything after that
is identical, because the geometry is read off the board rather than asked
for.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
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
    CONF_API_KEY,
    CONF_BLEND,
    CONF_CLOCK,
    CONF_CLOCK_REFRESH,
    CONF_DWELL,
    CONF_ENABLEMENT_TOKEN,
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
    SOURCE_DECLARED,
    SOURCE_LIST,
    SOURCE_TODO,
    SUBENTRY_SOURCE,
    TRANSPORT_CLOUD,
    TRANSPORT_LOCAL,
)
from .core.layout import fit
from .core.models import TIER_CONTENT, TIER_CRITICAL, TIER_TASK
from .transport.base import VestaboardAuthError, VestaboardError
from .transport.cloud import CloudTransport
from .transport.local import LocalTransport

TIER_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[TIER_CRITICAL, TIER_TASK, TIER_CONTENT],
        translation_key="tier",
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
            try:
                api_key = user_input.get(CONF_API_KEY)
                if not api_key:
                    api_key = await LocalTransport.async_enable(
                        session,
                        user_input[CONF_HOST],
                        user_input[CONF_ENABLEMENT_TOKEN],
                    )
                transport = LocalTransport(session, user_input[CONF_HOST], api_key)
                geometry = await transport.async_detect_geometry()
            except VestaboardAuthError:
                errors["base"] = "invalid_auth"
            except VestaboardError:
                errors["base"] = "cannot_connect"
            else:
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

    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        if user_input is not None:
            return self.async_update_reload_and_abort(entry, data_updates=user_input)
        key = (
            CONF_TOKEN
            if entry.data.get(CONF_TRANSPORT) == TRANSPORT_CLOUD
            else CONF_API_KEY
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(key): str}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return VestassistantOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry) -> dict[str, type]:
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
    }


class VestassistantOptionsFlow(OptionsFlow):
    """Dwell, quiet hours, summary, blend, and the built-in cards."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DWELL,
                        default=options.get(CONF_DWELL, DEFAULT_DWELL_MINUTES),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=240, step=1, unit_of_measurement="min"
                        )
                    ),
                    vol.Required(
                        CONF_SUMMARY_THRESHOLD,
                        default=options.get(
                            CONF_SUMMARY_THRESHOLD, DEFAULT_SUMMARY_THRESHOLD
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0, max=20, step=1)
                    ),
                    vol.Required(
                        CONF_SUMMARY_TEMPLATE,
                        default=options.get(
                            CONF_SUMMARY_TEMPLATE, DEFAULT_SUMMARY_TEMPLATE
                        ),
                    ): str,
                    vol.Optional(
                        CONF_QUIET_START,
                        description={
                            "suggested_value": options.get(CONF_QUIET_START)
                        },
                    ): selector.TimeSelector(),
                    vol.Optional(
                        CONF_QUIET_END,
                        description={"suggested_value": options.get(CONF_QUIET_END)},
                    ): selector.TimeSelector(),
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
                        CONF_CLOCK, default=options.get(CONF_CLOCK, False)
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_CLOCK_REFRESH,
                        default=options.get(CONF_CLOCK_REFRESH, DEFAULT_CLOCK_REFRESH),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=60, step=1, unit_of_measurement="min"
                        )
                    ),
                    vol.Required(
                        CONF_FORECAST, default=options.get(CONF_FORECAST, False)
                    ): selector.BooleanSelector(),
                    # Optional because the switch above may be off. Turning
                    # the forecast on without naming an entity simply
                    # contributes nothing, rather than failing setup.
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
    """Add a source: a list, a to-do list, or entities that declare cards."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if user_input is not None:
            kind = user_input[CONF_SOURCE_TYPE]
            self._kind = kind
            if kind == SOURCE_LIST:
                return await self.async_step_list()
            if kind == SOURCE_TODO:
                return await self.async_step_todo()
            return await self.async_step_declared()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCE_TYPE, default=SOURCE_LIST): (
                        selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[SOURCE_LIST, SOURCE_TODO, SOURCE_DECLARED],
                                translation_key="source_type",
                                mode=selector.SelectSelectorMode.LIST,
                            )
                        )
                    )
                }
            ),
        )

    async def async_step_list(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            entries = [
                line.strip()
                for line in user_input.get(CONF_ENTRIES, [])
                if line and line.strip()
            ]
            # Checked here rather than at render time: finding out a message
            # does not fit because it is garbled on the wall is the bad
            # version of this feedback loop.
            geometry = self._geometry()
            results = [
                fit(card.strip(), geometry)
                for line in entries
                for card in line.split("|")
            ]
            if any(r.error for r in results):
                errors[CONF_ENTRIES] = "invalid_character"
            elif any(not r.fits for r in results):
                errors[CONF_ENTRIES] = "does_not_fit"
            else:
                return self.async_create_entry(
                    title=user_input["name"],
                    data={
                        CONF_SOURCE_TYPE: SOURCE_LIST,
                        CONF_ENTRIES: entries,
                        CONF_TIER: user_input[CONF_TIER],
                    },
                )

        return self.async_show_form(
            step_id="list",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default="Messages"): str,
                    vol.Required(CONF_TIER, default=TIER_CONTENT): TIER_SELECTOR,
                    vol.Required(CONF_ENTRIES, default=[]): selector.TextSelector(
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
        if user_input is not None:
            return self.async_create_entry(
                title=user_input["name"],
                data={
                    CONF_SOURCE_TYPE: SOURCE_TODO,
                    CONF_ENTITY_ID: user_input[CONF_ENTITY_ID],
                    CONF_TIER: user_input[CONF_TIER],
                },
            )
        return self.async_show_form(
            step_id="todo",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default="To-do"): str,
                    vol.Required(CONF_ENTITY_ID): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="todo")
                    ),
                    vol.Required(CONF_TIER, default=TIER_TASK): TIER_SELECTOR,
                }
            ),
        )

    async def async_step_declared(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=user_input["name"],
                data={
                    CONF_SOURCE_TYPE: SOURCE_DECLARED,
                    CONF_ENTITY_ID: user_input.get(CONF_ENTITY_ID) or [],
                    CONF_TIER: user_input[CONF_TIER],
                },
            )
        return self.async_show_form(
            step_id="declared",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default="Declared cards"): str,
                    vol.Optional(CONF_ENTITY_ID): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["binary_sensor", "input_boolean", "sensor"],
                            multiple=True,
                        )
                    ),
                    vol.Required(CONF_TIER, default=TIER_TASK): TIER_SELECTOR,
                }
            ),
        )

    def _geometry(self):
        from .core.layout import NOTE

        entry = self._get_entry()
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is not None and coordinator.geometry is not None:
            return coordinator.geometry
        return NOTE
