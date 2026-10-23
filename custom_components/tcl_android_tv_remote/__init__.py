"""The TCL Android TV Remote integration."""

from __future__ import annotations

from asyncio import timeout
import logging

from androidtvremote2 import CannotConnect, ConnectionClosed, InvalidAuth

from homeassistant.const import CONF_HOST, CONF_NAME, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import (
    ADB_MODE_TLS,
    CONF_ADB_MODE,
    CONF_ADB_PORT,
    CONF_APPS,
    CONF_ENABLE_ADB,
    DOMAIN,
)
from .coordinator import AdbDataCoordinator, adb_issue_id
from .helpers import (
    RuntimeData,
    TclAndroidTvRemoteConfigEntry,
    create_adb,
    create_api,
    get_adb_mode,
    get_adb_port,
    get_enable_adb,
    get_enable_ime,
    get_keepalive_interval,
)
from .services import async_setup_services
from .sources import SourceManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.REMOTE,
    Platform.SELECT,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration (register services once)."""
    async_setup_services(hass)
    return True


# Options written by pre-release builds that no longer do anything
_REMOVED_OPTIONS = ("allowed_sources", "enforce_allowed")


async def async_migrate_entry(
    hass: HomeAssistant, entry: TclAndroidTvRemoteConfigEntry
) -> bool:
    """Migrate config entries to the current version."""
    if entry.version > 1:
        # Downgrade from a future version
        return False

    if entry.minor_version < 2:
        options = {
            k: v for k, v in entry.options.items() if k not in _REMOVED_OPTIONS
        }
        if options.get(CONF_ENABLE_ADB, True) and CONF_ADB_MODE not in options:
            # Record the mode that was previously inferred from the port
            options[CONF_ADB_MODE] = get_adb_mode(entry)
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)
        _LOGGER.debug("Migrated %s to version 1.2", entry.title)

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: TclAndroidTvRemoteConfigEntry
) -> bool:
    """Set up TCL Android TV Remote from a config entry."""
    api = create_api(hass, entry.data[CONF_HOST], get_enable_ime(entry))

    @callback
    def is_available_updated(is_available: bool) -> None:
        _LOGGER.info(
            "%s %s at %s",
            "Reconnected to" if is_available else "Disconnected from",
            entry.data[CONF_NAME],
            entry.data[CONF_HOST],
        )

    api.add_is_available_updated_callback(is_available_updated)

    try:
        async with timeout(5.0):
            await api.async_connect()
    except InvalidAuth as exc:
        raise ConfigEntryAuthFailed from exc
    except (CannotConnect, ConnectionClosed, TimeoutError) as exc:
        raise ConfigEntryNotReady from exc

    def reauth_needed() -> None:
        entry.async_start_reauth(hass)

    api.keep_reconnecting(reauth_needed)
    entry.async_on_unload(api.disconnect)

    adb = None
    coordinator: AdbDataCoordinator | None = None

    if get_enable_adb(entry):
        use_tls = get_adb_mode(entry) == ADB_MODE_TLS
        adb = create_adb(
            hass, entry.data[CONF_HOST], get_adb_port(entry), use_tls=use_tls
        )

        @callback
        def _save_port(port: int) -> None:
            # Persist a rediscovered Wireless debugging port without reloading
            hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_ADB_PORT: port}
            )

        coordinator = AdbDataCoordinator(
            hass,
            adb,
            get_keepalive_interval(entry),
            entry_id=entry.entry_id,
            device_name=entry.data.get(CONF_NAME, entry.title),
            on_port_changed=_save_port,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, adb_issue_id(entry.entry_id))

    entry.runtime_data = RuntimeData(
        api=api,
        sources=SourceManager(api, entry.options.get(CONF_APPS, {}), adb, coordinator),
        adb=adb,
        coordinator=coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if coordinator is not None:
        # Connecting can take up to ~30s when the TV is asleep or debugging is
        # off; don't hold up startup for it. Entities fill in on first refresh.
        entry.async_create_background_task(
            hass, coordinator.async_refresh(), f"{DOMAIN}_adb_first_refresh"
        )

    @callback
    def on_hass_stop(event: Event) -> None:
        api.disconnect()
        if adb is not None:
            hass.async_add_executor_job(adb.close)

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_hass_stop)
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: TclAndroidTvRemoteConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and entry.runtime_data.adb:
        await hass.async_add_executor_job(entry.runtime_data.adb.close)
    return unload_ok


async def async_remove_entry(
    hass: HomeAssistant, entry: TclAndroidTvRemoteConfigEntry
) -> None:
    """Clean up the repair issue when the entry is deleted."""
    ir.async_delete_issue(hass, DOMAIN, adb_issue_id(entry.entry_id))
