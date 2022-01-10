"""Support for the Roku media player."""
from __future__ import annotations

import datetime as dt
import logging

import voluptuous as vol

from urllib.parse import quote

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
)
from homeassistant.components.media_player.const import (
    MEDIA_TYPE_APP,
    MEDIA_TYPE_CHANNEL,
    SUPPORT_BROWSE_MEDIA,
    SUPPORT_NEXT_TRACK,
    SUPPORT_PAUSE,
    SUPPORT_PLAY,
    SUPPORT_PLAY_MEDIA,
    SUPPORT_PREVIOUS_TRACK,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_STEP,
)
from homeassistant.components.media_player.errors import BrowseError
from homeassistant.components.stream.const import (
    HLS_PROVIDER,
    FORMAT_CONTENT_TYPE
)
from homeassistant.const import (
    STATE_HOME,
    STATE_IDLE,
    STATE_ON,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_STANDBY,
)
from homeassistant.helpers import entity_platform
from homeassistant.helpers.network import is_internal_request

from . import roku_exception_handler
from .browse_media import build_item_response, library_payload
from .const import ATTR_KEYWORD, DOMAIN, SERVICE_SEARCH
from .coordinator import RokuDataUpdateCoordinator
from .entity import RokuEntity

_LOGGER = logging.getLogger(__name__)

SUPPORT_ROKU = (
    SUPPORT_PREVIOUS_TRACK
    | SUPPORT_NEXT_TRACK
    | SUPPORT_VOLUME_STEP
    | SUPPORT_VOLUME_MUTE
    | SUPPORT_SELECT_SOURCE
    | SUPPORT_PAUSE
    | SUPPORT_PLAY
    | SUPPORT_PLAY_MEDIA
    | SUPPORT_TURN_ON
    | SUPPORT_TURN_OFF
    | SUPPORT_BROWSE_MEDIA
)

SEARCH_SCHEMA = {vol.Required(ATTR_KEYWORD): str}


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Roku config entry."""
    coordinator: RokuDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    unique_id = coordinator.data.info.serial_number
    async_add_entities([RokuMediaPlayer(unique_id, coordinator)], True)

    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        SERVICE_SEARCH,
        SEARCH_SCHEMA,
        "search",
    )


class RokuMediaPlayer(RokuEntity, MediaPlayerEntity):
    """Representation of a Roku media player on the network."""

    def __init__(self, unique_id: str, coordinator: RokuDataUpdateCoordinator) -> None:
        """Initialize the Roku device."""
        super().__init__(
            coordinator=coordinator,
            device_id=unique_id,
        )

        self._attr_name = coordinator.data.info.name
        self._attr_unique_id = unique_id
        self._attr_supported_features = SUPPORT_ROKU

    def _media_playback_trackable(self) -> bool:
        """Detect if we have enough media data to track playback."""
        if self.coordinator.data.media is None or self.coordinator.data.media.live:
            return False

        return self.coordinator.data.media.duration > 0

    @property
    def device_class(self) -> str | None:
        """Return the class of this device."""
        if self.coordinator.data.info.device_type == "tv":
            return MediaPlayerDeviceClass.TV

        return MediaPlayerDeviceClass.RECEIVER

    @property
    def state(self) -> str | None:
        """Return the state of the device."""
        if self.coordinator.data.state.standby:
            return STATE_STANDBY

        if self.coordinator.data.app is None:
            return None

        if (
            self.coordinator.data.app.name == "Power Saver"
            or self.coordinator.data.app.screensaver
        ):
            return STATE_IDLE

        if self.coordinator.data.app.name == "Roku":
            return STATE_HOME

        if self.coordinator.data.media:
            if self.coordinator.data.media.paused:
                return STATE_PAUSED
            return STATE_PLAYING

        if self.coordinator.data.app.name:
            return STATE_ON

        return None

    @property
    def media_content_type(self) -> str | None:
        """Content type of current playing media."""
        if self.app_id is None or self.app_name in ("Power Saver", "Roku"):
            return None

        if self.app_id == "tvinput.dtv" and self.coordinator.data.channel is not None:
            return MEDIA_TYPE_CHANNEL

        return MEDIA_TYPE_APP

    @property
    def media_image_url(self) -> str | None:
        """Image url of current playing media."""
        if self.app_id is None or self.app_name in ("Power Saver", "Roku"):
            return None

        return self.coordinator.roku.app_icon_url(self.app_id)

    @property
    def app_name(self) -> str | None:
        """Name of the current running app."""
        if self.coordinator.data.app is not None:
            return self.coordinator.data.app.name

        return None

    @property
    def app_id(self) -> str | None:
        """Return the ID of the current running app."""
        if self.coordinator.data.app is not None:
            return self.coordinator.data.app.app_id

        return None

    @property
    def media_channel(self) -> str | None:
        """Return the TV channel currently tuned."""
        if self.app_id != "tvinput.dtv" or self.coordinator.data.channel is None:
            return None

        if self.coordinator.data.channel.name is not None:
            return f"{self.coordinator.data.channel.name} ({self.coordinator.data.channel.number})"

        return self.coordinator.data.channel.number

    @property
    def media_title(self) -> str | None:
        """Return the title of current playing media."""
        if self.app_id != "tvinput.dtv" or self.coordinator.data.channel is None:
            return None

        if self.coordinator.data.channel.program_title is not None:
            return self.coordinator.data.channel.program_title

        return None

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        if self._media_playback_trackable():
            return self.coordinator.data.media.duration

        return None

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds."""
        if self._media_playback_trackable():
            return self.coordinator.data.media.position

        return None

    @property
    def media_position_updated_at(self) -> dt.datetime | None:
        """When was the position of the current playing media valid."""
        if self._media_playback_trackable():
            return self.coordinator.data.media.at

        return None

    @property
    def source(self) -> str | None:
        """Return the current input source."""
        if self.coordinator.data.app is not None:
            return self.coordinator.data.app.name

        return None

    @property
    def source_list(self) -> list:
        """List of available input sources."""
        return ["Home"] + sorted(app.name for app in self.coordinator.data.apps)

    @roku_exception_handler
    async def search(self, keyword):
        """Emulate opening the search screen and entering the search keyword."""
        await self.coordinator.roku.search(keyword)

    async def async_get_browse_image(
        self,
        media_content_type: str,
        media_content_id: str,
        media_image_id: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Fetch media browser image to serve via proxy."""
        if media_content_type == MEDIA_TYPE_APP and media_content_id:
            image_url = self.coordinator.roku.app_icon_url(media_content_id)
            return await self._async_fetch_image(image_url)

        return (None, None)

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Implement the websocket media browsing helper."""
        is_internal = is_internal_request(self.hass)

        def _get_thumbnail_url(
            media_content_type, media_content_id, media_image_id=None
        ):
            if is_internal:
                if media_content_type == MEDIA_TYPE_APP and media_content_id:
                    return self.coordinator.roku.app_icon_url(media_content_id)
                return None

            return self.get_browse_image_url(
                media_content_type, media_content_id, media_image_id
            )

        if media_content_type in [None, "library"]:
            return library_payload(self.coordinator, _get_thumbnail_url)

        payload = {
            "search_type": media_content_type,
            "search_id": media_content_id,
        }
        response = build_item_response(self.coordinator, payload, _get_thumbnail_url)

        if response is None:
            raise BrowseError(
                f"Media not found: {media_content_type} / {media_content_id}"
            )

        return response

    @roku_exception_handler
    async def async_turn_on(self) -> None:
        """Turn on the Roku."""
        await self.coordinator.roku.remote("poweron")
        await self.coordinator.async_request_refresh()

    @roku_exception_handler
    async def async_turn_off(self) -> None:
        """Turn off the Roku."""
        await self.coordinator.roku.remote("poweroff")
        await self.coordinator.async_request_refresh()

    @roku_exception_handler
    async def async_media_pause(self) -> None:
        """Send pause command."""
        if self.state not in (STATE_STANDBY, STATE_PAUSED):
            await self.coordinator.roku.remote("play")
            await self.coordinator.async_request_refresh()

    @roku_exception_handler
    async def async_media_play(self) -> None:
        """Send play command."""
        if self.state not in (STATE_STANDBY, STATE_PLAYING):
            await self.coordinator.roku.remote("play")
            await self.coordinator.async_request_refresh()

    @roku_exception_handler
    async def async_media_play_pause(self) -> None:
        """Send play/pause command."""
        if self.state != STATE_STANDBY:
            await self.coordinator.roku.remote("play")
            await self.coordinator.async_request_refresh()

    @roku_exception_handler
    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        await self.coordinator.roku.remote("reverse")
        await self.coordinator.async_request_refresh()

    @roku_exception_handler
    async def async_media_next_track(self) -> None:
        """Send next track command."""
        await self.coordinator.roku.remote("forward")
        await self.coordinator.async_request_refresh()

    @roku_exception_handler
    async def async_mute_volume(self, mute) -> None:
        """Mute the volume."""
        await self.coordinator.roku.remote("volume_mute")
        await self.coordinator.async_request_refresh()

    @roku_exception_handler
    async def async_volume_up(self) -> None:
        """Volume up media player."""
        await self.coordinator.roku.remote("volume_up")

    @roku_exception_handler
    async def async_volume_down(self) -> None:
        """Volume down media player."""
        await self.coordinator.roku.remote("volume_down")

    @roku_exception_handler
    async def async_play_media(self, media_type: str, media_id: str, **kwargs) -> None:
        """Tune to channel."""
        if media_type not in (MEDIA_TYPE_APP, MEDIA_TYPE_CHANNEL, FORMAT_CONTENT_TYPE[HLS_PROVIDER]):
            _LOGGER.error(
                "Invalid media type %s. Only %s and %s are supported",
                media_type,
                MEDIA_TYPE_APP,
                MEDIA_TYPE_CHANNEL,
            )
            return

        if media_type == MEDIA_TYPE_APP:
            media_array = media_id.split(",")
            if len(media_array) > 1:
                app_id = media_array[0].strip()
                content_id = media_array[1].strip()
                _LOGGER.info("Launching Roku app %s with deep link %s", app_id, content_id)
                await self.coordinator.roku.launch(app_id, {"contentId": quote(content_id, safe="")})
            else:
                _LOGGER.info("Launching Roku app %s", media_id)
                await self.coordinator.roku.launch(media_id)
        elif media_type == FORMAT_CONTENT_TYPE[HLS_PROVIDER]:
            _LOGGER.info("Launching Roku side loaded app with deep link %s", media_id)
            await self.coordinator.roku.launch("dev", {"contentId": quote(media_id, safe="")})
        elif media_type == MEDIA_TYPE_CHANNEL:
            _LOGGER.info("Switching to Roku TV channel %s", media_id)
            await self.coordinator.roku.tune(media_id)

        await self.coordinator.async_request_refresh()

    @roku_exception_handler
    async def async_select_source(self, source: str) -> None:
        """Select input source."""
        if source == "Home":
            await self.coordinator.roku.remote("home")

        appl = next(
            (
                app
                for app in self.coordinator.data.apps
                if source in (app.name, app.app_id)
            ),
            None,
        )

        if appl is not None:
            await self.coordinator.roku.launch(appl.app_id)

        await self.coordinator.async_request_refresh()
