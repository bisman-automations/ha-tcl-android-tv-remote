"""Fixtures for TCL Android TV Remote tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tcl_android_tv_remote.const import (
    ADB_MODE_CLASSIC,
    CONF_ADB_MODE,
    CONF_ADB_PORT,
    CONF_ENABLE_ADB,
    DOMAIN,
)

HOST = "192.0.2.10"
MAC = "1A:2B:3C:4D:5E:6F"
NAME = "TCL Living Room"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations, mock_async_zeroconf):
    """Enable custom integrations and keep zeroconf off the network."""
    return


@pytest.fixture
def mock_api() -> Generator[MagicMock]:
    """A fake androidtvremote2.AndroidTVRemote."""
    api = MagicMock()
    api.async_connect = AsyncMock()
    api.async_generate_cert_if_missing = AsyncMock(return_value=True)
    api.async_get_name_and_mac = AsyncMock(return_value=(NAME, MAC))
    api.async_start_pairing = AsyncMock()
    api.async_finish_pairing = AsyncMock()
    api.device_info = {"manufacturer": "TCL", "model": "65S5"}
    api.is_on = True
    api.current_app = "com.netflix.ninja"
    api.volume_info = {"level": 10, "max": 100, "muted": False}
    with (
        patch(
            "custom_components.tcl_android_tv_remote.create_api", return_value=api
        ),
        patch(
            "custom_components.tcl_android_tv_remote.config_flow.create_api",
            return_value=api,
        ),
    ):
        yield api


@pytest.fixture
def no_mdns() -> Generator[None]:
    """Skip mDNS port discovery."""
    with (
        patch(
            "custom_components.tcl_android_tv_remote.config_flow.discover_pairing_port",
            AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.tcl_android_tv_remote.config_flow.discover_connect_port",
            AsyncMock(return_value=None),
        ),
    ):
        yield


def make_entry(options: dict | None = None) -> MockConfigEntry:
    """Config entry for a paired TV (ADB off unless options say otherwise)."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="1a:2b:3c:4d:5e:6f",
        title=NAME,
        data={CONF_HOST: HOST, CONF_NAME: NAME, CONF_MAC: MAC},
        options={CONF_ENABLE_ADB: False} if options is None else options,
    )


CLASSIC_OPTIONS = {
    CONF_ENABLE_ADB: True,
    CONF_ADB_MODE: ADB_MODE_CLASSIC,
    CONF_ADB_PORT: 5555,
}
