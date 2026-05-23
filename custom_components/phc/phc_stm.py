"""API for communicating with PHC STM."""

import asyncio
import base64
from dataclasses import dataclass
from enum import Enum
import io
import zipfile

import aiohttp
from aiohttp.web import HTTPError
import defusedxml.ElementTree as ET

from .custom_http import RawTCPClientSession


@dataclass
class _PhcLight:
    name: str
    module: int
    channel: int
    dimmer: bool

    brightness: int | None = None
    is_on: bool = False

    def update(self, status, brightness):
        self.brightness = brightness
        self.is_on = status


@dataclass
class _PhcScreen:
    name: str
    module: int
    channel: int


class XMLException(Exception):
    """XML is not as expected."""


class _PhcNormalCmd(Enum):
    STATUS = 1
    ON = 2  # Confirmed by app
    OFF = 3  # Confirmed by app
    ON_LOCKED = 4  # I did this and could not disable. Also not with toggle. Did some random command and eventually toggle worked.
    OFF_LOCKED = 5
    TOGGLE = 6  # Confirmed by app
    ULOCK = 7
    ON_DELAY = 8  # Takes a second parameter that is the time in seconds and then a 0
    OFF_DELAY = 9  # Takes a second parameter that is the time in seconds and then a 0
    ON_TIMED = 10  # Takes a second parameter that is the time in seconds and then a 0
    OFF_TIMED = 11  # Takes a second parameter that is the time in seconds and then a 0s. For some reason also toggles a dimmer and keeps its state
    TOGGLE_DELAY_LOCKED = (
        12  # Takes a second parameter that is the time in seconds and then a 0
    )
    TOGGLE_TIMED_LOCKED = (
        13  # Takes a second parameter that is the time in seconds and then a 0
    )
    LOCK = 14
    LOCK_RUNNING_TIME = (
        15  # Takes a second parameter that is the time in seconds and then a 0
    )
    ADD_RUNNING_TIME = (
        16  # Takes a second parameter that is the time in seconds and then a 0
    )
    SET_RUNNING_TIME = (
        17  # Takes a second parameter that is the time in seconds and then a 0
    )
    STOP_RUNNING_TIME = (
        18  # Stops the timer: means the action that is taken at the end is not taken
    )


class _PhcDimmerCmd(Enum):
    STATUS = 1
    MAX_WITH_MEMORY = 2
    MAX_NO_MEMORY = 3
    OFF = 4
    CHANGE_MAX_WITH_MEMORY = 5  # Toggle between off and on and save max in memory
    CHANGE_MAX_NO_MEMORY = 6  # Toggle between off and on?
    CHANGE_DIMMING_DIRECTION = 7  # Not entirely clear
    DIM_UP = 8
    DIM_DOWN = 9
    SAVE_MEM = 10
    TOGGLE_WITH_MEM = 11  # Means when turned on used the memory value.
    TURN_ON_WITH_MEMORY = 12
    SAVE_DIA_1 = 13  # ??
    TOGGLE_DIA_1 = 14
    ON_DIA_1 = 15
    SAVE_DIA_2 = 16  # ??
    TOGGLE_DIA_2 = 17
    ON_DIA_2 = 18
    SAVE_DIA_3 = 19  # ??
    TOGGLE_DIA_3 = 20
    ON_DIA_3 = 21
    DIMMER = 22  # Then follows dimmer value which is uint8 then follows 0


class _JrmCmd(Enum):
    """I believe movement command take prio as first argument and time as second."""

    STOP = 2
    CHANGE_UP_STOP = 3  # If moving stop, else go up.
    CHANGE_DOWN_STOP = 4
    UP = 5
    DOWN = 6
    TIP_UP = 7  # small adjustment
    TIP_DOWN = 8
    LOCK_PRIO = 9  # STOP these priorities from access
    UNLOCK_PRIO = 10
    LEARNING_ON = 11  # Unsure if supported
    LEARNING_OFF = 12
    SET_PRIO = 13
    RESET_PRIO = 14
    SENSOR_ROLLUIK_UP = 15
    SENSOR_JALOEZIE_UP = 16  # Same as above except slight movement opposite at the end
    SENSOR_ROLLUIK_DOWN = 17
    SENSOR_JALOZIE_DOWN = 18


class PhcStm:
    """API for the PHC STM controler."""

    def __init__(self, host, logger) -> None:
        """Init the controller."""
        self.host = host
        # Dict[tuple[mod, cha], _PhcLight]
        self.lights: dict[tuple[int, int], _PhcLight] = {}
        self.screens: list[_PhcScreen] = []
        self.lock = asyncio.Lock()
        self.logger = logger

    # ip = "http://192.168.0.83:6680"

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
    }

    # First i4 is stm always 0
    send_telegram_payload = """\
    <?xml version="1.0" encoding="UTF-8"?>
    <methodCall>
    <methodName>service.stm.sendTelegram</methodName>
    <params>
    <param><value><i4>0</i4></value></param>
    <param><value><i4>{module}</i4></value></param>
    <param><value><i4>{command}</i4></value></param>
    {params}
    </params>
    </methodCall>
    """

    read_file = """\
    <?xml version="1.0" encoding="UTF-8"?>
    <methodCall>
    <methodName>service.stm.readFile</methodName>
    <params>
    <param><value><i4>0</i4></value></param>
    <param><value><i4>{part}</i4></value></param>
    <param><value><i4>1</i4></value></param>
    </params>
    </methodCall>
    """

    async def _cmd(
        self, module, command, extra_data: list[int] | None = None
    ) -> list[int]:
        async with self.lock:
            async with asyncio.timeout(30):
                if extra_data is None:
                    extra_data = []
                data = self.send_telegram_payload.format(
                    module=module,
                    command=command,
                    params="\n".join(
                        [
                            f"<param><value><i4>{e}</i4></value></param>"
                            for e in extra_data
                        ]
                    ),
                )
                async with RawTCPClientSession(self.host) as session:
                    response = await session.post(
                        headers=self.headers,
                        data=data,
                    )
        root = ET.fromstring(response.content)
        return [int(i4.text) for i4 in root.findall(".//i4")]

    async def turn_on(self, module: int, channel: int):
        """Instruct the light to turn on."""
        if self.lights[(module, channel)].dimmer:
            await self._cmd(
                module, self.create_command(channel, _PhcDimmerCmd.TURN_ON_WITH_MEMORY)
            )
        else:
            await self._cmd(module, self.create_command(channel, _PhcNormalCmd.ON))

    async def turn_off(self, module: int, channel: int):
        """Instruct the light to turn off."""
        cmd = _PhcNormalCmd.OFF
        if self.lights[(module, channel)].dimmer:
            cmd = _PhcDimmerCmd.OFF
        await self._cmd(module, self.create_command(channel, cmd))

    async def dim(self, module, channel, brightness):
        """Set the brightness of this channel to `brightness`."""
        await self._cmd(
            module, self.create_command(channel, _PhcDimmerCmd.DIMMER), [brightness, 0]
        )

    def get_light_status(self, mask, channel):
        """Get the status of the specified channel out of the the returned value."""
        return ((mask >> channel) & 1) == 1

    async def open_screen(self, module: int, channel: int):
        """Open screen."""
        # I dont fully understand what 0,0,10 means. 10 has something to do with the time. But unclear what exactly
        returned = await self._cmd(
            module,
            self.create_command(channel, _JrmCmd.UP),
            [0, 0, 10],
        )
        self.logger.info(returned)

    async def close_screen(self, module: int, channel: int):
        """Close screen."""
        # I dont fully understand what 0,0,10 means. 10 has something to do with the time. But unclear what exactly
        returned = await self._cmd(
            module,
            self.create_command(channel, _JrmCmd.DOWN),
            [0, 0, 10],
        )
        self.logger.info(returned)

    async def stop_screen(self, module: int, channel: int):
        """Stop opening or closing screen."""
        # I dont fully understand what 0 means?
        returned = await self._cmd(
            module, self.create_command(channel, _JrmCmd.STOP), [0]
        )
        self.logger.info(returned)

    async def get_status(self, module, channel, is_dimmer: bool) -> tuple:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.

        Return value is (on: bool, brightness: int | None)
        """
        try:
            values = await self._cmd(
                module, self.create_command(channel, _PhcNormalCmd.STATUS)
            )
            if is_dimmer and len(values) >= 7:
                light_status = self.get_light_status(values[6], channel)
                brightness = values[4 + channel]
            else:
                light_status = self.get_light_status(values[4], channel)
                brightness = None

            self.lights[(module, channel)].update(light_status, brightness)
        except HTTPError as err:
            raise HTTPError(f"Error communicating with API: {err}") from err
        else:
            return light_status, brightness

    async def update_all(self):
        """Update the status of all the lights."""
        for light in self.lights:
            await self.get_status(light.module, light.channel, light.dimmer)

    def create_command(self, channel: int, cmd: _PhcNormalCmd) -> int:
        """Create the command to execute for this channel."""
        return (channel << 5) | cmd.value

    def extract_bin(self, xml):
        """Extract and decode the base64 bin to text."""
        # Find the struct member with the name "bin"
        root = ET.fromstring(xml)
        bin_value = None
        for member in root.findall(".//member"):
            name = member.find("name")
            if name is not None and name.text == "bin":
                bin_value_elem = member.find("./value/base64")
                if bin_value_elem is not None:
                    bin_value = bin_value_elem.text
                    break
        if bin_value is None:
            raise XMLException
        return base64.b64decode(bin_value)

    def insert_light(self, mod: int, cha: int, dimmer: bool, name: str):
        """Insert a light into the stm."""
        log_string = f"Found light[{name} MOD{mod}, CHA[{cha}]]"
        self.logger.info(log_string)
        self.lights[(mod, cha)] = _PhcLight(name, mod, cha, dimmer)

    def extract_lights(self, xml):
        """Extract the lights from the project."""
        root = ET.fromstring(xml)
        for ausgang in root.findall(".//MODS[@grp='Ausgangsmodule']"):
            for module in ausgang.findall(".//MOD[@name='AMD230_10']"):
                mod_id = int(module.get("adr"))
                node = module.find(".//CHAS[@grp='Ausgang']")
                if node is None:
                    continue
                for channel in node.findall(".//CHA"):
                    if channel.get("visu") == "false":
                        continue
                    cha_id = int(channel.get("adr"))
                    name = channel.text

                    self.insert_light(mod_id + 64, cha_id, False, name)

            for module in ausgang.findall(".//MOD[@name='JRM']"):
                mod_id = int(module.get("adr"))
                node = module.find(".//CHAS[@grp='Ausgang']")
                if node is None:
                    continue
                for channel in node.findall(".//CHA"):
                    if channel.get("visu") == "false":
                        continue
                    cha_id = int(channel.get("adr"))
                    name = channel.text
                    self.screens.append(_PhcScreen(name, mod_id + 64, cha_id))

        for dimmer in root.findall(".//MODS[@grp='Dimmermodule']"):
            for module in dimmer.findall(".//MOD[@name]"):
                if not module.get("name").startswith("DIM_"):
                    continue
                mod_id = int(module.get("adr"))
                node = module.find(".//CHAS[@grp='Ausgang']")
                if node is None:
                    continue
                for channel in node.findall(".//CHA"):
                    if channel.get("visu") == "false":
                        continue
                    cha_id = int(channel.get("adr"))
                    name = channel.text

                    self.insert_light(mod_id + 160, cha_id, True, name)

    async def download_project(self) -> bool:
        """Download the project from the stm and parse it."""
        async with self.lock:
            self.logger.info("Downloading project")
            try:
                async with RawTCPClientSession(self.host) as session:
                    response1 = await session.post(
                        headers=self.headers,
                        data=self.read_file.format(part=0),
                    )
                    response2 = await session.post(
                        headers=self.headers,
                        data=self.read_file.format(part=1),
                    )
                    zip_file = self.extract_bin(response1.content) + self.extract_bin(
                        response2.content
                    )
                    self.logger.info("zipfile length", extra={"length": len(zip_file)})
                    zip_stream = io.BytesIO(zip_file)
                    with zipfile.ZipFile(zip_stream, "r") as zip_file:
                        for file_name in zip_file.namelist():
                            self.logger.info(file_name)
                            if file_name == "project.ppfx":
                                with zip_file.open(file_name) as file:
                                    content = file.read()
                                    self.extract_lights(content)

            except aiohttp.ClientError, OSError:
                return False
            else:
                return True

    def get_lights(self):
        """Get all the lights in this stm."""
        return self.lights.values()

    def get_covers(self):
        """Get all the discoverd covers."""
        return self.screens
