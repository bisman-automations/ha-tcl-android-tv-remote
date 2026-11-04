"""Button entities for TCL Android TV Remote."""

from __future__ import annotations

import logging
from typing import override

from androidtvremote2 import AndroidTVRemote

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import TclAndroidTvRemoteBaseEntity
from .helpers import TclAndroidTvRemoteConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Unique id of the Find remote button removed in 1.1.2. The class used
# `_key = "find_remote"`, and `_TclButton` stores `{entry unique id}_btn_{key}`.
# Setup still recognizes that id so an existing install can drop the orphan.
_RETIRED_FIND_REMOTE_UNIQUE_ID_SUFFIX = "_btn_find_remote"


def async_remove_retired_find_remote_button(
    hass: HomeAssistant, config_entry: TclAndroidTvRemoteConfigEntry
) -> None:
    """Remove this entry's retired Find remote button from the entity registry.

    The button is no longer created. Without this, Home Assistant keeps the
    old registry row and shows it as unavailable. The match is this config
    entry, the button domain, and this integration's platform, so a renamed
    entity id is still removed and nothing else is.
    """
    unique = config_entry.unique_id
    if not unique:
        return
    retired_unique_id = f"{unique}{_RETIRED_FIND_REMOTE_UNIQUE_ID_SUFFIX}"
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, config_entry.entry_id):
        if (
            entity.domain == "button"
            and entity.platform == DOMAIN
            and entity.unique_id == retired_unique_id
        ):
            _LOGGER.info("Removing retired Find remote button %s", entity.entity_id)
            registry.async_remove(entity.entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: TclAndroidTvRemoteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons. ADB-backed buttons only exist when ADB is enabled."""
    # Before entities are added, so the platform does not restore the retired one.
    async_remove_retired_find_remote_button(hass, config_entry)
    runtime = config_entry.runtime_data
    entities: list[ButtonEntity] = [TclHomeButton(runtime.api, config_entry)]
    if runtime.coordinator is not None:
        entities += [
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
