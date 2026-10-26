"""Sensors for TCL Android TV Remote."""

from __future__ import annotations

from typing import Any, override

from androidtvremote2 import AndroidTVRemote

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import AdbDataCoordinator
from .entity import TclAndroidTvRemoteBaseEntity
from .helpers import TclAndroidTvRemoteConfigEntry

PARALLEL_UPDATES = 0

ADB_STATUSES = [
    "connected",
    "disconnected",
    "unauthorized",
    "offline",
    "timeout",
    "error",
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: TclAndroidTvRemoteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors (only when ADB is enabled)."""
    runtime = config_entry.runtime_data
    if runtime.coordinator is None:
        return
    async_add_entities(
        [
            TclCurrentSourceSensor(runtime.coordinator, runtime.api, config_entry),
            TclAdbStatusSensor(runtime.coordinator, runtime.api, config_entry),
        ]
    )


class _CoordinatedEntity(
    CoordinatorEntity[AdbDataCoordinator], TclAndroidTvRemoteBaseEntity
):
    def __init__(
        self,
        coordinator: AdbDataCoordinator,
        api: AndroidTVRemote,
        config_entry: TclAndroidTvRemoteConfigEntry,
        key: str,
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        TclAndroidTvRemoteBaseEntity.__init__(self, api, config_entry)
        self._attr_unique_id = f"{config_entry.unique_id}_{key}"


class TclCurrentSourceSensor(_CoordinatedEntity, SensorEntity):
    """Friendly name of the current HDMI input or app."""

    _attr_translation_key = "current_source"

    def __init__(self, coordinator, api, config_entry) -> None:
        super().__init__(coordinator, api, config_entry, "current_source")
        self._sources = config_entry.runtime_data.sources

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
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
    def native_value(self) -> str | None:
        return self._sources.current_source()


class TclAdbStatusSensor(_CoordinatedEntity, SensorEntity):
    """ADB connection status."""

    _attr_translation_key = "adb_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ADB_STATUSES

    def __init__(self, coordinator, api, config_entry) -> None:
        super().__init__(coordinator, api, config_entry, "adb_status")

    @property
    @override
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if not data:
            return None
        return data.status if data.status in ADB_STATUSES else "error"

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data:
            return {}
        return {"port": data.port, "last_error": data.last_error}
