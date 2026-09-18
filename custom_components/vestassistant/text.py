"""A box you can type a message into, and have it appear on the board."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import VestassistantConfigEntry, VestassistantCoordinator
from .core.layout import fit
from .entity import VestassistantEntity

#: Home Assistant caps a text entity's value at 255 characters. A board holds
#: far less than that, so the real limit is the board's own capacity.
HA_MAX = 255

#: The characters a Vestaboard can physically show, plus braces for colour
#: codes like {63} and a bar for a row break. Lower case is allowed because
#: the board uppercases everything anyway. Built by hand from
#: ``vesta.chars.PRINTABLE`` rather than generated at import time, so a
#: change to that table is a visible diff here.
#: The frontend rejects anything outside it as you type; laying the message
#: out is still what decides whether it actually fits.
PATTERN = r"""[ A-Za-z!"#$%&'()+,\-./0123456789:;=?@°{}|]*"""

PARALLEL_UPDATES = 0  # every write is serialised by the coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestassistantConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([MessageText(entry.runtime_data)])


class MessageText(VestassistantEntity, TextEntity):
    """Type here and it goes up now, then the rotation resumes.

    Deliberately a pin rather than an item: somebody typing at the board
    wants to see it immediately, not queued behind whatever is up. Clearing
    the box hands the board straight back.
    """

    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_pattern = PATTERN

    def __init__(self, coordinator: VestassistantCoordinator) -> None:
        super().__init__(coordinator, "message")
        geometry = coordinator.geometry
        # A Note holds 45 cells and a Flagship 132, so the ceiling follows the
        # board rather than Home Assistant's generic 255.
        self._attr_native_max = min(HA_MAX, geometry.capacity) if geometry else HA_MAX

    @property
    def native_value(self) -> str:
        return self.coordinator.typed_message

    async def async_set_value(self, value: str) -> None:
        message = value.strip()
        if not message:
            self.coordinator.typed_message = ""
            await self.coordinator.async_release()
            return

        geometry = self.coordinator.geometry
        if geometry is not None:
            # Say why it will not work while the box still has the text in
            # it, rather than logging a failure the typist never sees.
            result = fit(message, geometry, shorten=True)
            if result.error:
                raise ServiceValidationError(
                    f"The board cannot show that: {result.error}"
                )
            if not result.fits:
                raise ServiceValidationError(
                    f"That is too long for a {geometry.name}, even shortened. "
                    f"It needs {result.rows_needed} rows and there are "
                    f"{geometry.rows}."
                )

        landed = await self.coordinator.async_pin(
            message, self.coordinator.scheduler_config.dwell
        )
        if not landed:
            raise ServiceValidationError(
                "The board did not take the message. Check the log for why."
            )
        self.coordinator.typed_message = message
