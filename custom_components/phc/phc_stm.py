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
class PhcLight:
    name: str
    module: int
    channel: int
    dimmer: bool

    brightness: int | None = None
    is_on: bool = False

    def update(self, status, brightness):
        self.brightness = brightness
        self.is_on = status


class XMLException(Exception):
    """XML is not as expected."""


class _PhcCmd(Enum):
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
    DIMMER = 22  # Seemingly. Then follows dimmer value which is uint8 then follows 0


class PhcStm:
    """API for the PHC STM controler."""

    def __init__(self, host, logger) -> None:
        """Init the controller."""
        self.host = host
        # Dict[tuple[mod, cha], PhcLight]
        self.lights: dict[tuple[int, int], PhcLight] = {}
        # TODO: need cover here as well? How to seperate cover from the thing
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
            if extra_data is None:
                extra_data = []
            data = self.send_telegram_payload.format(
                module=module,
                command=command,
                params="\n".join(
                    [f"<param><value><i4>{e}</i4></value></param>" for e in extra_data]
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
                module, self.create_command(channel, _PhcCmd.OFF_TIMED)
            )  # Seems like my interpretation of the commands is off.
        else:
            await self._cmd(module, self.create_command(channel, _PhcCmd.ON))

    async def toggle(self, module: int, channel: int):
        """Instruct the light to turn on."""
        await self._cmd(module, self.create_command(channel, _PhcCmd.TOGGLE))

    async def turn_off(self, module: int, channel: int):
        """Instruct the light to turn off."""
        cmd = _PhcCmd.OFF
        if self.lights[(module, channel)].dimmer:
            cmd = (
                _PhcCmd.OFF_TIMED
            )  # Seems like my interpretation of the commands is off.
        await self._cmd(module, self.create_command(channel, cmd))

    async def dim(self, module, channel, brightness):
        """Set the brightness of this channel to `brightness`."""
        await self._cmd(
            module, self.create_command(channel, _PhcCmd.DIMMER), [brightness, 0]
        )

    def get_light_status(self, mask, channel):
        """Get the status of the specified channel out of the the returned value."""
        return ((mask >> channel) & 1) == 1

    async def get_status(self, module, channel, is_dimmer: bool) -> tuple:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.

        Return value is (on: bool, brightness: int | None)
        """
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with asyncio.timeout(30):
                values = await self._cmd(
                    module, self.create_command(channel, _PhcCmd.STATUS)
                )
                if is_dimmer and len(values) >= 7:
                    light_status = self.get_light_status(values[6], channel)
                    brightness = values[4 + channel]
                else:
                    light_status = self.get_light_status(values[4], channel)
                    brightness = None

                self.lights[(module, channel)].update(light_status, brightness)
                return light_status, brightness
        except HTTPError as err:
            raise HTTPError(f"Error communicating with API: {err}") from err

    async def update_all(self):
        """Update the status of all the lights."""
        for light in self.lights:
            await self.get_status(light.module, light.channel, light.dimmer)

    def create_command(self, channel: int, cmd: _PhcCmd) -> int:
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
            raise XMLException()

        return base64.b64decode(bin_value)

    def insert_light(self, mod: int, cha: int, dimmer: bool, name: str):
        """Insert a light into the stm."""
        self.lights[(mod, cha)] = PhcLight(name, mod, cha, dimmer)

    def extract_lights(self, xml):
        """Extract the lights from the project."""
        root = ET.fromstring(xml)
        for member in root.findall(".//TOOL"):
            name = member.get("bez")
            dimmer: bool = False
            node = member.find(".//NODE/VAR[@modGrp='Ausgangsmodule']")
            if node is None:
                node = member.find(".//NODE/VAR[@modGrp='Dimmermodule']")
                dimmer = True

            if node is not None:
                mod_value = node.get("mod")
                cha_value = node.get("cha")
                self.insert_light(int(mod_value), int(cha_value), dimmer, name)

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
                            if file_name == "project.tpfx":
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
