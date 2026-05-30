"""The phc integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .phc_stm import PhcStm

_LOGGER = logging.getLogger("phc")

PLATFORMS: list[Platform] = [Platform.COVER, Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up phc from a config entry."""

    hass.data.setdefault(DOMAIN, {})
    ip = entry.data.get(CONF_HOST)
    stm = PhcStm(ip, _LOGGER)
    succes = await stm.download_project()
    if not succes:
        raise ConnectionError

    hass.data[DOMAIN][entry.entry_id] = stm
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
