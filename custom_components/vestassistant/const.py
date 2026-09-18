"""Constants for Vestassistant."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "vestassistant"

CONF_TRANSPORT: Final = "transport"
CONF_HOST: Final = "host"
CONF_API_KEY: Final = "api_key"
CONF_TOKEN: Final = "token"
CONF_ENABLEMENT_TOKEN: Final = "enablement_token"

TRANSPORT_LOCAL: Final = "local"
TRANSPORT_CLOUD: Final = "cloud"

CONF_DWELL: Final = "dwell_minutes"
CONF_SUMMARY_THRESHOLD: Final = "summary_threshold"
CONF_SUMMARY_TEMPLATE: Final = "summary_template"
CONF_QUIET_START: Final = "quiet_start"
CONF_QUIET_END: Final = "quiet_end"
CONF_BLEND: Final = "blend"

CONF_CLOCK: Final = "clock_enabled"
CONF_CLOCK_REFRESH: Final = "clock_refresh_minutes"
CONF_FORECAST: Final = "forecast_enabled"
CONF_FORECAST_ENTITY: Final = "forecast_entity"
CONF_BOARD_COLOUR: Final = "board_colour"
BOARD_BLACK: Final = "black"
BOARD_WHITE: Final = "white"

CONF_SOURCE_TYPE: Final = "source_type"
CONF_ENTRIES: Final = "entries"
CONF_TIER: Final = "tier"
CONF_COLOUR: Final = "colour"
CONF_ENTITY_ID: Final = "entity_id"
CONF_PATTERNS: Final = "patterns"
CONF_HUES: Final = "hues"
CONF_LOOKAHEAD_DAYS: Final = "lookahead_days"
CONF_MAX_EVENTS: Final = "max_events"

SUBENTRY_SOURCE: Final = "source"
SOURCE_LIST: Final = "list"
SOURCE_TODO: Final = "todo"
SOURCE_DECLARED: Final = "declared"
SOURCE_PATTERN: Final = "pattern"
SOURCE_CALENDAR: Final = "calendar"

DEFAULT_DWELL_MINUTES: Final = 20
DEFAULT_SUMMARY_THRESHOLD: Final = 3
DEFAULT_SUMMARY_TEMPLATE: Final = "YOU HAVE {n} THINGS THAT NEED YOU."
DEFAULT_BLEND: Final = "alternate"
DEFAULT_LOOKAHEAD_DAYS: Final = 2
DEFAULT_MAX_EVENTS: Final = 3

#: Minutes between rewrites of the clock card while it is on the board. Every
#: rewrite is a physical flip, so this is deliberately not one minute.
DEFAULT_CLOCK_REFRESH: Final = 5

#: How often the board is read back, to notice somebody posting from the
#: Vestaboard app and to keep the preview image honest.
POLL_INTERVAL: Final = timedelta(seconds=60)

STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = f"{DOMAIN}.state"

SERVICE_ADD_ITEM: Final = "add_item"
SERVICE_REMOVE_ITEM: Final = "remove_item"
SERVICE_NEXT: Final = "next"
SERVICE_PIN: Final = "pin"
SERVICE_VALIDATE: Final = "validate"

ATTR_ITEM_ID: Final = "item_id"
ATTR_MESSAGE: Final = "message"
ATTR_TIER: Final = "tier"
ATTR_COLOUR: Final = "colour"
ATTR_TTL: Final = "ttl"
ATTR_EXPIRE_WHEN: Final = "expire_when"
ATTR_DURATION: Final = "duration"
ATTR_DWELL: Final = "dwell"
