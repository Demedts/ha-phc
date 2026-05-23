"""Control PHC cover from home assistant."""

from datetime import timedelta
import logging

# Import the device class from the component that you want to support
from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.components.cover.const import CoverDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .phc_stm import PhcStm

_LOGGER = logging.getLogger("phc")


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the PHC platform."""
    # Setup connection with devices/cloud
    _LOGGER.info("Setting up platform")
    stm = hass.data[DOMAIN][config_entry.entry_id]

    covers = [
        PhcCover(stm, cover.name, cover.module, cover.channel)
        for cover in stm.get_covers()
    ]
    added_covers = ", ".join(
        [f"{cover.name}: {cover.module}, {cover.channel}" for cover in stm.get_covers()]
    )
    log = f"Added {len(covers)} covers: {added_covers}"
    _LOGGER.info(log)
    async_add_entities(covers, update_before_add=True)
    return True


class PhcCover(CoverEntity):
    """Class represents a PHC cover.

    Can go up and down but does not know state.
    """

    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )
    _attr_should_poll = False
    _attr_device_class = CoverDeviceClass.SHADE

    def __init__(self, stm: PhcStm, name: str, mod: int, cha: int) -> None:
        """Init the cover."""
        self.name = name
        self._stm = stm
        self._mod = mod
        self._cha = cha
        self._attr_unique_id = f"PHC_SCREEN_{self._mod}_{self._cha}"

    @property
    def is_closed(self):
        """Return if the cover is closed."""
        return None

    async def async_open_cover(self, **kwargs):
        """Open the cover."""
        # send open command to device
        await self._stm.open_screen(self._mod, self._cha)

    async def async_close_cover(self, **kwargs):
        """Close the cover."""
        # send close command to device
        await self._stm.close_screen(self._mod, self._cha)

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        # send stop command to device
        await self._stm.stop_screen(self._mod, self._cha)
