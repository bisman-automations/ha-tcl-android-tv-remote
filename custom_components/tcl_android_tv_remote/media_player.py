"""Media player support for TCL Android TV Remote."""

import asyncio
from typing import Any, override

from androidtvremote2 import AndroidTVRemote, ConnectionClosed

try:
    from androidtvremote2 import VolumeInfo
except ImportError:  # older library versions exported volume as plain dict
    from typing import TypedDict

    class VolumeInfo(TypedDict):
        level: int
        max: int
        muted: bool


from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .adb import MediaMetadata
from .const import CONF_APP_ICON, CONF_APP_NAME, DOMAIN
from .entity import TclAndroidTvRemoteBaseEntity
from .helpers import TclAndroidTvRemoteConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: TclAndroidTvRemoteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Android TV media player entity based on a config entry."""
    api = config_entry.runtime_data.api
    async_add_entities([TclAndroidTvRemoteMediaPlayerEntity(api, config_entry)])


class TclAndroidTvRemoteMediaPlayerEntity(
    TclAndroidTvRemoteBaseEntity, MediaPlayerEntity
):
    """TCL Android TV Remote Media Player Entity."""

    _attr_name = None  # main feature: entity is named after the device
    _attr_assumed_state = True
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = (
        MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(
        self, api: AndroidTVRemote, config_entry: TclAndroidTvRemoteConfigEntry
    ) -> None:
        """Initialize the entity."""
        super().__init__(api, config_entry)
        self._config_entry = config_entry
        self._sources = config_entry.runtime_data.sources

        # This task is needed to create a job that sends a key press
        # sequence that can be canceled if concurrency occurs
        self._channel_set_task: asyncio.Task | None = None
        self._attr_app_id: str | None = None
        self._attr_app_name: str | None = None

    def _update_current_app(self, current_app: str) -> None:
        """Update current app info."""
        self._attr_app_id = current_app
        self._attr_app_name = (
            self._apps[current_app].get(CONF_APP_NAME, current_app)
            if current_app in self._apps
            else current_app
        )

    def _update_volume_info(self, volume_info: VolumeInfo) -> None:
        """Update volume info."""
        if volume_info.get("max"):
            self._attr_volume_level = volume_info["level"] / volume_info["max"]
            self._attr_is_volume_muted = volume_info["muted"]
        else:
            self._attr_volume_level = None
            self._attr_is_volume_muted = None

    @callback
    def _current_app_updated(self, current_app: str) -> None:
        """Update the state when the current app changes."""
        self._update_current_app(current_app)
        self.async_write_ha_state()

    @callback
    def _volume_info_updated(self, volume_info: VolumeInfo) -> None:
        """Update the state when the volume info changes."""
        self._update_volume_info(volume_info)
        self.async_write_ha_state()

    @property
    @override
    def source(self) -> str | None:
        """Active HDMI input when on one, else the current app."""
        return self._sources.current_source()

    @property
    @override
    def source_list(self) -> list[str]:
        """HDMI inputs (via ADB) followed by configured apps."""
        return self._sources.source_list()

    @override
    async def async_select_source(self, source: str) -> None:
        """Select input source: HDMI via ADB, apps via Remote protocol."""
        await self._sources.async_select(source)
        self.async_write_ha_state()

    @override
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()

        if self._api.current_app is not None:
            self._update_current_app(self._api.current_app)
        if self._api.volume_info is not None:
            self._update_volume_info(self._api.volume_info)

        self._api.add_current_app_updated_callback(self._current_app_updated)
        self._api.add_volume_info_updated_callback(self._volume_info_updated)

        coordinator = self._config_entry.runtime_data.coordinator
        if coordinator:
            self.async_on_remove(
                coordinator.async_add_listener(self.async_write_ha_state)
            )

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Remove callbacks."""
        await super().async_will_remove_from_hass()

        self._api.remove_current_app_updated_callback(self._current_app_updated)
        self._api.remove_volume_info_updated_callback(self._volume_info_updated)

    @property
    @override
    def state(self) -> MediaPlayerState:
        """Return the state of the device.

        Power comes from the remote protocol; playback state from ADB only
        while the TV is on (media_session keeps stale sessions when off).
        """
        if not self._attr_is_on:
            return MediaPlayerState.OFF
        media = self._media()
        if media and media.playback_state == "playing":
            return MediaPlayerState.PLAYING
        if media and media.playback_state == "paused":
            return MediaPlayerState.PAUSED
        return MediaPlayerState.ON

    @property
    @override
    def media_title(self) -> str | None:
        media = self._media()
        return media.title if media else None

    @property
    @override
    def media_artist(self) -> str | None:
        media = self._media()
        return media.artist if media else None

    @property
    @override
    def media_album_name(self) -> str | None:
        media = self._media()
        return media.album if media else None

    @property
    @override
    def media_image_url(self) -> str | None:
        media = self._media()
        return media.image_url if media else None

    def _media(self) -> MediaMetadata | None:
        if not self._attr_is_on:
            return None
        runtime = self._config_entry.runtime_data
        if runtime.coordinator and runtime.coordinator.data:
            return runtime.coordinator.data.media
        return None

    @override
    async def async_turn_on(self) -> None:
        """Turn the Android TV on."""
        if not self._attr_is_on:
            self._send_key_command("POWER")

    @override
    async def async_turn_off(self) -> None:
        """Turn the Android TV off."""
        if self._attr_is_on:
            self._send_key_command("POWER")

    @override
    async def async_volume_up(self) -> None:
        """Turn volume up for media player."""
        self._send_key_command("VOLUME_UP")

    @override
    async def async_volume_down(self) -> None:
        """Turn volume down for media player."""
        self._send_key_command("VOLUME_DOWN")

    @override
    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        if mute != self.is_volume_muted:
            self._send_key_command("VOLUME_MUTE")

    @override
    async def async_media_play(self) -> None:
        """Send play command."""
        self._send_key_command("MEDIA_PLAY")

    @override
    async def async_media_pause(self) -> None:
        """Send pause command."""
        self._send_key_command("MEDIA_PAUSE")

    @override
    async def async_media_play_pause(self) -> None:
        """Send play/pause command."""
        self._send_key_command("MEDIA_PLAY_PAUSE")

    @override
    async def async_media_stop(self) -> None:
        """Send stop command."""
        self._send_key_command("MEDIA_STOP")

    @override
    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        self._send_key_command("MEDIA_PREVIOUS")

    @override
    async def async_media_next_track(self) -> None:
        """Send next track command."""
        self._send_key_command("MEDIA_NEXT")

    @override
    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Play a piece of media."""
        if media_type == MediaType.CHANNEL:
            if not media_id.isnumeric():
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_channel",
                    translation_placeholders={"media_id": media_id},
                )
            if self._channel_set_task:
                self._channel_set_task.cancel()
            self._channel_set_task = asyncio.create_task(
                self._send_key_commands(list(media_id))
            )
            await self._channel_set_task
            return

        if media_type in [MediaType.URL, MediaType.APP]:
            self._sources.launch_app(media_id)
            return

        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="invalid_media_type",
            translation_placeholders={"media_type": media_type},
        )

    @override
    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse apps."""
        children = [
            BrowseMedia(
                media_class=MediaClass.APP,
                media_content_type=MediaType.APP,
                media_content_id=app_id,
                title=app.get(CONF_APP_NAME, ""),
                thumbnail=app.get(CONF_APP_ICON, ""),
                can_play=False,
                can_expand=False,
            )
            for app_id, app in self._apps.items()
        ]
        return BrowseMedia(
            title="Applications",
            media_class=MediaClass.DIRECTORY,
            media_content_id="apps",
            media_content_type=MediaType.APPS,
            children_media_class=MediaClass.APP,
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def _send_key_commands(
        self, key_codes: list[str], delay_secs: float = 0.1
    ) -> None:
        """Send a key press sequence to Android TV.

        The delay is necessary because device may ignore
        some commands if we send the sequence without delay.
        """
        try:
            for key_code in key_codes:
                self._api.send_key_command(key_code)
                await asyncio.sleep(delay_secs)
        except ConnectionClosed as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="connection_closed"
            ) from exc
