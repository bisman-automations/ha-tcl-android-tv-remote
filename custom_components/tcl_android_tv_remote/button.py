"""Button entities for TCL Android TV Remote."""

from __future__ import annotations

from typing import override

from androidtvremote2 import AndroidTVRemote

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import TclAndroidTvRemoteBaseEntity
from .helpers import TclAndroidTvRemoteConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: TclAndroidTvRemoteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons. ADB-backed buttons only exist when ADB is enabled."""
    runtime = config_entry.runtime_data
    entities: list[ButtonEntity] = [TclHomeButton(runtime.api, config_entry)]
    if runtime.coordinator is not None:
        entities += [
            TclFindRemoteButton(runtime.api, config_entry),
            TclRefreshHdmiButton(runtime.api, config_entry),
            TclRebuildSourcesButton(runtime.api, config_entry),
        ]
    async_add_entities(entities)


class _TclButton(TclAndroidTvRemoteBaseEntity, ButtonEntity):
    _key: str

    def __init__(
        self, api: AndroidTVRemote, config_entry: TclAndroidTvRemoteConfigEntry
    ) -> None:
        super().__init__(api, config_entry)
        self._runtime = config_entry.runtime_data
        self._attr_unique_id = f"{config_entry.unique_id}_btn_{self._key}"
        self._attr_translation_key = self._key


class TclHomeButton(_TclButton):
    """Send HOME key."""

    _key = "home"

    @override
    async def async_press(self) -> None:
        self._send_key_command("HOME")


class TclFindRemoteButton(_TclButton):
    """Ask the TV to locate its remote (KEYCODE_PAIRING over ADB).

    Support depends on the TV model and remote; on some firmwares this opens
    the remote pairing screen instead.
    """

    _key = "find_remote"

    @override
    async def async_press(self) -> None:
        coordinator = self._runtime.coordinator
        assert coordinator is not None
        if (
            await coordinator.async_adb_command("input keyevent KEYCODE_PAIRING")
            is None
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="adb_command_failed",
                translation_placeholders={
                    "name": coordinator.device_name,
                    "error": coordinator.adb.last_error or "unknown",
                },
            )


class TclRefreshHdmiButton(_TclButton):
    """Force HDMI source rediscovery."""

    _key = "refresh_hdmi"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @override
    async def async_press(self) -> None:
        coordinator = self._runtime.coordinator
        assert coordinator is not None
        await coordinator.async_refresh_hdmi()


class TclRebuildSourcesButton(_TclButton):
    """Forget every saved HDMI input and custom name, then discover again."""

    _key = "rebuild_sources"
    _attr_entity_category = EntityCategory.CONFIG

    @override
    async def async_press(self) -> None:
        await self._runtime.sources.async_rebuild()
