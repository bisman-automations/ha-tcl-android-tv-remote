"""Helper functions for TCL Android TV Remote integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any

from androidtvremote2 import AndroidTVRemote

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import STORAGE_DIR

from .adb import AdbClient
from .const import (
    ADB_MODE_CLASSIC,
    ADB_MODE_TLS,
    CONF_ADB_MODE,
    CONF_ADB_PORT,
    CONF_ADB_PORT_DEFAULT,
    CONF_ENABLE_ADB,
    CONF_ENABLE_ADB_DEFAULT,
    CONF_ENABLE_IME,
    CONF_ENABLE_IME_DEFAULT_VALUE,
    CONF_KEEPALIVE_INTERVAL,
    CONF_KEEPALIVE_INTERVAL_DEFAULT,
    KEEPALIVE_INTERVAL_MAX,
    KEEPALIVE_INTERVAL_MIN,
)

if TYPE_CHECKING:
    from .coordinator import AdbDataCoordinator
    from .sources import SourceManager

_LOGGER = logging.getLogger(__name__)

MDNS_ADB_TLS_PAIRING = "_adb-tls-pairing._tcp.local."
MDNS_ADB_TLS_CONNECT = "_adb-tls-connect._tcp.local."


@dataclass
class RuntimeData:
    """Runtime objects for a config entry."""

    api: AndroidTVRemote
    sources: SourceManager
    adb: AdbClient | None = None
    coordinator: AdbDataCoordinator | None = None


type TclAndroidTvRemoteConfigEntry = ConfigEntry[RuntimeData]


def create_api(hass: HomeAssistant, host: str, enable_ime: bool) -> AndroidTVRemote:
    """Create an AndroidTVRemote instance."""
    return AndroidTVRemote(
        client_name="Home Assistant",
        certfile=hass.config.path(STORAGE_DIR, "tcl_android_tv_remote_cert.pem"),
        keyfile=hass.config.path(STORAGE_DIR, "tcl_android_tv_remote_key.pem"),
        host=host,
        loop=hass.loop,
        enable_ime=enable_ime,
    )


def create_adb(
    hass: HomeAssistant, host: str, port: int, *, use_tls: bool
) -> AdbClient:
    """Create an ADB client (not yet connected; key dir is created on first use)."""
    return AdbClient(
        host=host,
        port=port,
        adbkey=hass.config.path(STORAGE_DIR, "tcl_android_tv_remote_adbkey"),
        use_tls=use_tls,
    )


def get_enable_ime(entry: ConfigEntry) -> bool:
    """Get value of enable_ime option or its default value."""
    return bool(entry.options.get(CONF_ENABLE_IME, CONF_ENABLE_IME_DEFAULT_VALUE))


def get_enable_adb(entry: ConfigEntry) -> bool:
    """Whether ADB / HDMI control is enabled."""
    return bool(entry.options.get(CONF_ENABLE_ADB, CONF_ENABLE_ADB_DEFAULT))


def get_adb_port(entry: ConfigEntry) -> int:
    """ADB port (0 = TLS connect port not known yet, discover it)."""
    try:
        return int(entry.options.get(CONF_ADB_PORT, CONF_ADB_PORT_DEFAULT))
    except (TypeError, ValueError):
        return CONF_ADB_PORT_DEFAULT


def get_adb_mode(entry: ConfigEntry) -> str:
    """ADB transport mode.

    Entries created before adb_mode existed used the port to decide: anything
    other than 5555 meant a Wireless debugging (TLS) port.
    """
    mode = entry.options.get(CONF_ADB_MODE)
    if mode in (ADB_MODE_TLS, ADB_MODE_CLASSIC):
        return mode
    return ADB_MODE_CLASSIC if get_adb_port(entry) == 5555 else ADB_MODE_TLS


def get_keepalive_interval(entry: ConfigEntry) -> int:
    """ADB keep-alive / coordinator interval in seconds."""
    try:
        value = int(
            entry.options.get(CONF_KEEPALIVE_INTERVAL, CONF_KEEPALIVE_INTERVAL_DEFAULT)
        )
    except (TypeError, ValueError):
        value = CONF_KEEPALIVE_INTERVAL_DEFAULT
    return max(KEEPALIVE_INTERVAL_MIN, min(value, KEEPALIVE_INTERVAL_MAX))


async def _async_discover_port(
    hass: HomeAssistant, host: str, service_type: str, timeout: float
) -> int | None:
    """Listen briefly for an mDNS service advertised by host and return its port."""
    from zeroconf import ServiceBrowser, ServiceStateChange

    from homeassistant.components import zeroconf as ha_zeroconf

    found: dict[str, int] = {}

    def _on_change(
        zeroconf: Any,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change is ServiceStateChange.Removed:
            return
        try:
            info = zeroconf.get_service_info(service_type, name, timeout=1000)
        except Exception:  # noqa: BLE001
            return
        if not info:
            return
        if host in (info.parsed_addresses() or []) or host in (info.server or ""):
            found["port"] = info.port

    zc = await ha_zeroconf.async_get_instance(hass)
    browser = ServiceBrowser(zc, service_type, handlers=[_on_change])
    try:
        await asyncio.sleep(timeout)
    finally:
        await hass.async_add_executor_job(browser.cancel)
    return found.get("port")


async def discover_pairing_port(
    hass: HomeAssistant, host: str, timeout: float = 2.0
) -> int | None:
    """Find the Android 11+ wireless debugging pairing port for host via mDNS."""
    try:
        return await _async_discover_port(hass, host, MDNS_ADB_TLS_PAIRING, timeout)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Pairing port discovery failed", exc_info=True)
        return None


async def discover_connect_port(
    hass: HomeAssistant, host: str, timeout: float = 3.0
) -> int | None:
    """Find the Android 11+ wireless debugging TLS connect port for host via mDNS.

    Android picks a new random port every time Wireless debugging restarts
    (TV reboot, toggle), so this is re-run whenever a TLS connect fails.
    """
    try:
        return await _async_discover_port(hass, host, MDNS_ADB_TLS_CONNECT, timeout)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Connect port discovery failed", exc_info=True)
        return None
