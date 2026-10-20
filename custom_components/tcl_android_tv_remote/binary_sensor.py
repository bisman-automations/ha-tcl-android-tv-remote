"""Binary sensors for TCL Android TV Remote."""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import AdbDataCoordinator
from .entity import TclAndroidTvRemoteBaseEntity
from .helpers import TclAndroidTvRemoteConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: TclAndroidTvRemoteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    runtime = config_entry.runtime_data
    if runtime.coordinator is None:
        return
    async_add_entities(
        [TclAdbConnectedBinarySensor(runtime.coordinator, runtime.api, config_entry)]
    )


class TclAdbConnectedBinarySensor(
    CoordinatorEntity[AdbDataCoordinator],
    TclAndroidTvRemoteBaseEntity,
    BinarySensorEntity,
):
    """Shows whether ADB is currently connected.

    Attributes stay small and only change when the status does, so the
    recorder isn't written to on every poll. Full detail is in diagnostics.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "adb_connected"

    def __init__(
        self,
        coordinator: AdbDataCoordinator,
        api,
        config_entry: TclAndroidTvRemoteConfigEntry,
    ) -> None:
        """Initialize."""
        CoordinatorEntity.__init__(self, coordinator)
        TclAndroidTvRemoteBaseEntity.__init__(self, api, config_entry)
        self._attr_unique_id = f"{config_entry.unique_id}_adb_connected"
        self._use_tls = coordinator.adb.use_tls

    @property
    @override
    def is_on(self) -> bool:
        """Return True when ADB is available."""
        data = self.coordinator.data
        return bool(data and data.available)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data:
            return {}
        return {
            "status": data.status,
            "port": data.port,
            "hint": _status_hint(data.status, self._use_tls),
        }


def _status_hint(status: str | None, use_tls: bool) -> str | None:
    """Short human guidance based on ADB status."""
    if status == "connected":
        return None
    if status == "unauthorized":
        return (
            "The TV has not accepted this key. Revoke debugging authorizations in "
            "Developer options, reload the integration and accept the prompt."
        )
    if status == "timeout":
        return "ADB timed out. The TV may be asleep or the network is slow."
    if use_tls:
        return (
            "Cannot reach the TV over Wireless debugging. Make sure it is on; "
            "re-pair from the integration options if it was turned off."
        )
    return "Cannot reach the TV on the ADB port. Make sure Network debugging is on."
