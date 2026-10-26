"""Tests for mDNS port discovery and option helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from zeroconf import ServiceStateChange

from custom_components.tcl_android_tv_remote.const import (
    ADB_MODE_CLASSIC,
    ADB_MODE_TLS,
    CONF_ADB_MODE,
    CONF_ADB_PORT,
)
from custom_components.tcl_android_tv_remote.helpers import (
    MDNS_ADB_TLS_CONNECT,
    discover_connect_port,
    discover_pairing_port,
    get_adb_mode,
)
from homeassistant.core import HomeAssistant

from .conftest import HOST, make_entry


def _fake_browser(advertised: list[tuple[str, int]]):
    """ServiceBrowser stand-in that reports each (address, port) right away."""

    class Browser:
        def __init__(self, zc, service_type, handlers):
            for i, (address, port) in enumerate(advertised):
                info = MagicMock(port=port, server=f"adb-{i}.local.")
                info.parsed_addresses.return_value = [address]
                zc.get_service_info.return_value = info
                handlers[0](
                    zeroconf=zc,
                    service_type=service_type,
                    name=f"adb-{i}.{service_type}",
                    state_change=ServiceStateChange.Added,
                )

        def cancel(self):
            pass

    return Browser


async def _discover(hass, advertised, func=discover_connect_port):
    zc = MagicMock()
    with (
        patch("zeroconf.ServiceBrowser", _fake_browser(advertised)),
        patch(
            "homeassistant.components.zeroconf.async_get_instance",
            AsyncMock(return_value=zc),
        ),
    ):
        return await func(hass, HOST, timeout=0)


async def test_discover_port_matches_host(hass: HomeAssistant) -> None:
    # Another device's service is ignored; ours is picked up
    port = await _discover(hass, [("192.0.2.99", 1111), (HOST, 44491)])
    assert port == 44491


async def test_discover_port_none_when_absent(hass: HomeAssistant) -> None:
    assert await _discover(hass, [("192.0.2.99", 1111)]) is None
    assert await _discover(hass, [], discover_pairing_port) is None


async def test_discover_port_errors_return_none(hass: HomeAssistant) -> None:
    with patch(
        "homeassistant.components.zeroconf.async_get_instance",
        AsyncMock(side_effect=RuntimeError("no zeroconf")),
    ):
        assert await discover_connect_port(hass, HOST, timeout=0) is None


def test_service_type_constant() -> None:
    assert MDNS_ADB_TLS_CONNECT == "_adb-tls-connect._tcp.local."


def test_adb_mode_inferred_for_old_entries() -> None:
    assert get_adb_mode(make_entry({CONF_ADB_PORT: 5555})) == ADB_MODE_CLASSIC
    assert get_adb_mode(make_entry({CONF_ADB_PORT: 44491})) == ADB_MODE_TLS
    assert get_adb_mode(make_entry({})) == ADB_MODE_CLASSIC
    assert (
        get_adb_mode(make_entry({CONF_ADB_PORT: 5555, CONF_ADB_MODE: ADB_MODE_TLS}))
        == ADB_MODE_TLS
    )
