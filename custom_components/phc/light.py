"""Control PHC stm from home assistant."""

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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN
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
    stm = hass.data[DOMAIN][config_entry.entry_id]
    lights = []
    dimmer_lights = []
    coordinators = {}
    for light in stm.get_lights():
        _LOGGER.info(
            "Adding PHC_LIGHT: %s, %s, %s", light.name, light.module, light.channel
        )
        if light.dimmer:
            dimmer_lights.append(
                PhcDimmerLight(stm, light.name, light.module, light.channel)
            )
        else:
            if light.module not in coordinators:
                coordinators[light.module] = PhcLightCoordinator(
                    hass, config_entry, stm, light.module
                )
                await coordinators[light.module].async_config_entry_first_refresh()
            lights.append(
                PhcLight(
                    stm,
                    coordinators[light.module],
                    light.name,
                    light.module,
                    light.channel,
                )
            )
    async_add_entities(dimmer_lights, update_before_add=True)
    async_add_entities(lights, update_before_add=False)
    return True


class PhcDimmerLight(LightEntity):
    """Class representing a PHC Dimmer light.

    This will provide the operations for this light.
    """

    _entity_registry_enabled_default = True

    def __init__(self, stm: PhcStm, name: str, module: int, channel: int) -> None:
        """Init the light."""
        super().__init__()
        self._name = name
        self._module = module
        self._channel = channel
        self._stm = stm

        self._attr_is_on = False
        self._attr_unique_id = f"PHC_LIGHT_{self._module}_{self._channel}"
        self._attr_brightness = 0

    @property
    def name(self) -> str:
        """Return the display name of this light."""
        return self._name

    @property
    def color_mode(self) -> ColorMode:
        """Supports BRIGHTNESS."""
        return ColorMode.BRIGHTNESS

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Supports BRIGHTNESS."""
        return {ColorMode.BRIGHTNESS}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if not brightness:
            await self._stm.turn_on(self._module, self._channel)
        else:
            await self._stm.dim(self._module, self._channel, brightness)
        await asyncio.sleep(0.5)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        await self._stm.turn_off(self._module, self._channel)
        self._attr_is_on = False
        self._attr_brightness = 0
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update entity."""
        try:
            data = await self._stm.get_status(self._module, self._channel, True)
        except HTTPError:
            self._attr_available = False
        else:
            self._attr_available = True
            self._attr_is_on = data[0]
            self._attr_brightness = data[1]


class PhcLightCoordinator(DataUpdateCoordinator):
    """Coordinator for binary output."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, stm: PhcStm, module: int
    ) -> None:
        """Init the class."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"PHC_MODULE_{module}",
            update_interval=SCAN_INTERVAL,
        )
        self._stm = stm
        self._module = module

    async def _async_update_data(self):
        try:
            return await self._stm.get_module_status(self._module)
        except HTTPError:
            raise UpdateFailed(retry_after=600) from HTTPError


class PhcLight(CoordinatorEntity, LightEntity):
    """Class representing a PHC non dimmable light.

    This will provide the operations for this light.
    """

    _entity_registry_enabled_default = True

    def __init__(
        self,
        stm: PhcStm,
        coordinator: PhcLightCoordinator,
        name: str,
        module: int,
        channel: int,
    ) -> None:
        """Init the light."""
        super().__init__(coordinator=coordinator)
        self._name = name
        self._module = module
        self._channel = channel
        self._stm = stm

        self._attr_unique_id = f"PHC_LIGHT_{self._module}_{self._channel}"
        self._attr_brightness = None

    @property
    def name(self) -> str:
        """Return the display name of this light."""
        return self._name

    @property
    def color_mode(self) -> ColorMode:
        """Supports ONOFF."""
        return ColorMode.ONOFF

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Supports ONOFF."""
        return {ColorMode.ONOFF}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        await self._stm.turn_on(self._module, self._channel)
        await asyncio.sleep(0.5)
        self._attr_is_on = True
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        await self._stm.turn_off(self._module, self._channel)
        await asyncio.sleep(0.5)
        self._attr_is_on = False
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update entity."""
        self._attr_available = True

        self._attr_is_on = self.coordinator.data[self._channel]
        self.async_write_ha_state()
