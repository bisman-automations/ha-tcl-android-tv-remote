"""Select entity for TV source (HDMI + apps)."""

from __future__ import annotations

from typing import override

from androidtvremote2 import AndroidTVRemote

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import TclAndroidTvRemoteBaseEntity
from .helpers import TclAndroidTvRemoteConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: TclAndroidTvRemoteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the source select."""
    async_add_entities([TclSourceSelect(config_entry.runtime_data.api, config_entry)])


class TclSourceSelect(TclAndroidTvRemoteBaseEntity, SelectEntity):
    """Dropdown of HDMI inputs and configured apps."""

    _attr_translation_key = "source"

    def __init__(
        self, api: AndroidTVRemote, config_entry: TclAndroidTvRemoteConfigEntry
    ) -> None:
        super().__init__(api, config_entry)
        self._runtime = config_entry.runtime_data
        self._sources = config_entry.runtime_data.sources
        self._attr_unique_id = f"{config_entry.unique_id}_source_select"

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if coordinator := self._runtime.coordinator:
            self.async_on_remove(
                coordinator.async_add_listener(self.async_write_ha_state)
            )
        self._api.add_current_app_updated_callback(self._app_updated)

    @override
    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        self._api.remove_current_app_updated_callback(self._app_updated)

    @callback
    def _app_updated(self, _app: str) -> None:
        self.async_write_ha_state()

    @property
    @override
    def available(self) -> bool:
        return super().available and bool(self._sources.source_list())

    @property
    @override
    def options(self) -> list[str]:
        return self._sources.source_list()

    @property
    @override
    def current_option(self) -> str | None:
        current = self._sources.current_source()
        return current if current in self.options else None

    @override
    async def async_select_option(self, option: str) -> None:
        await self._sources.async_select(option)
        self.async_write_ha_state()
