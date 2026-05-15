"""Control PHC stm from home assistant."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from aiohttp.web import HTTPError

# Import the device class from the component that you want to support
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    # PLATFORM_SCHEMA as LIGHT_PLATFORM_SCHEMA,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .phc_stm import PhcStm

_LOGGER = logging.getLogger("phc")
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the PHC platform."""
    # Setup connection with devices/cloud
    _LOGGER.info("Setting up platform")
    ip = config_entry.data.get(CONF_HOST)
    stm = PhcStm(ip, _LOGGER)
    succes = await stm.download_project()
    if not succes:
        raise ConnectionError

    lights = [
        PhcLight(stm, light.name, light.module, light.channel, light.dimmer)
        for light in stm.get_lights()
    ]
    added_lights = ", ".join(
        [f"{light.name}: {light.module}, {light.channel}" for light in lights]
    )
    log = f"Added {len(lights)} lights: {added_lights}"
    _LOGGER.info(log)
    async_add_entities(lights, update_before_add=True)
    return True


class PhcLight(LightEntity):
    """Class representing a PHC light.

    This will provide the operations for this light.
    """

    _entity_registry_enabled_default = True

    def __init__(
        self, stm: PhcStm, name: str, module: int, channel: int, is_dimmer=False
    ) -> None:
        """Init the light."""
        super().__init__()
        self._name = name
        self.module = module
        self.channel = channel
        self._is_dimmer = is_dimmer
        self._stm = stm

        self._attr_is_on = False
        self._attr_unique_id = f"PHC_LIGHT_{self.module}_{self.channel}"
        if self._is_dimmer:
            self._attr_brightness = 0
        else:
            self._attr_brightness = None

    @property
    def name(self) -> str:
        """Return the display name of this light."""
        return self._name

    @property
    def color_mode(self) -> ColorMode:
        """Supports BRIGHTNESS or only ONOFF."""
        if self._is_dimmer:
            return ColorMode.BRIGHTNESS
        return ColorMode.ONOFF

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Supports BRIGHTNESS or only ONOFF."""
        if self._is_dimmer:
            return {ColorMode.BRIGHTNESS}
        return {ColorMode.ONOFF}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if not brightness or not self._is_dimmer:
            await self._stm.turn_on(self.module, self.channel)
        else:
            await self._stm.dim(self.module, self.channel, brightness)
        await asyncio.sleep(0.5)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        await self._stm.turn_off(self.module, self.channel)
        self._attr_is_on = False
        if self._is_dimmer:
            self._attr_brightness = 0
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update entity."""
        try:
            data = await self._stm.get_status(
                self.module, self.channel, self._is_dimmer
            )
        except HTTPError:
            self._attr_available = False
        else:
            self._attr_available = True
            self._attr_is_on = data[0]
            self._attr_brightness = data[1]
