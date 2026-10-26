"""Config and options flow tests."""

from __future__ import annotations

from ipaddress import ip_address
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.tcl_android_tv_remote.const import (
    ADB_MODE_CLASSIC,
    ADB_MODE_TLS,
    ADB_PORT_DISCOVER,
    CONF_ADB_MODE,
    CONF_ADB_PORT,
    CONF_APPS,
    CONF_ENABLE_ADB,
    DOMAIN,
)
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .conftest import HOST, MAC, make_entry

pytestmark = pytest.mark.usefixtures("mock_api", "no_mdns")


@pytest.fixture(autouse=True)
def no_setup():
    with (
        patch(
            "custom_components.tcl_android_tv_remote.async_setup_entry",
            AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.tcl_android_tv_remote.async_unload_entry",
            AsyncMock(return_value=True),
        ),
    ):
        yield


async def _to_adb_menu(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["step_id"] == "pair"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pin": "123456"}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "adb_setup"
    return result


async def test_user_flow_classic_adb(hass: HomeAssistant) -> None:
    result = await _to_adb_menu(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "adb_classic"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {
        CONF_ENABLE_ADB: True,
        CONF_ADB_MODE: ADB_MODE_CLASSIC,
        CONF_ADB_PORT: 5555,
    }


async def test_user_flow_skip_adb(hass: HomeAssistant) -> None:
    """Skipping must not require pairing fields and must leave ADB off."""
    result = await _to_adb_menu(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "adb_none"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {CONF_ENABLE_ADB: False}


async def test_user_flow_wireless_pairing(hass: HomeAssistant) -> None:
    result = await _to_adb_menu(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "adb_wireless"}
    )
    assert result["step_id"] == "adb_wireless"

    adb = MagicMock()
    adb.pair_wireless.return_value = False
    adb.last_error = "Pairing failed: bad code"
    with patch(
        "custom_components.tcl_android_tv_remote.config_flow.create_adb",
        return_value=adb,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"pairing_port": 41745, "pairing_code": "000000"}
        )
        assert result["errors"] == {"base": "pair_failed"}
        assert result["description_placeholders"]["detail"] == adb.last_error

        adb.pair_wireless.return_value = True
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"pairing_port": 41745, "pairing_code": "123456"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # No connect port given or discovered: the coordinator will find it
    assert result["options"] == {
        CONF_ENABLE_ADB: True,
        CONF_ADB_MODE: ADB_MODE_TLS,
        CONF_ADB_PORT: ADB_PORT_DISCOVER,
    }


def _zeroconf(name: str) -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address(HOST),
        ip_addresses=[ip_address(HOST)],
        hostname="tv.local.",
        name=f"{name}._androidtvremote2._tcp.local.",
        port=6466,
        properties={"bt": MAC},
        type="_androidtvremote2._tcp.local.",
    )


async def test_zeroconf_ignores_non_tcl(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf("SHIELD"),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_tcl_device"


async def test_zeroconf_offers_tcl(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf("TCL 65S5"),
    )
    assert result["step_id"] == "zeroconf_confirm"


async def test_zeroconf_updates_host_of_configured_tv(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    info = _zeroconf("Living Room")  # custom name, still matched by MAC
    info.ip_address = ip_address("192.0.2.99")
    info.ip_addresses = [ip_address("192.0.2.99")]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
    )
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "192.0.2.99"


async def test_options_default_apps_not_readded(hass: HomeAssistant) -> None:
    """Saving settings must not bring back preset apps the user deleted."""
    entry = make_entry({CONF_ENABLE_ADB: False, CONF_APPS: {}})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "apps"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_APPS not in entry.options

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "apps"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"add_default_apps": True}
    )
    assert "com.netflix.ninja" in entry.options[CONF_APPS]


async def test_options_add_and_delete_app(hass: HomeAssistant) -> None:
    entry = make_entry({CONF_ENABLE_ADB: False})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "apps"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_APPS: "add_new"}
    )
    assert result["step_id"] == "app"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"app_id": "com.plexapp.android", "app_name": "Plex"}
    )
    assert entry.options[CONF_APPS]["com.plexapp.android"]["app_name"] == "Plex"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "apps"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_APPS: "com.plexapp.android"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"app_delete": True}
    )
    assert CONF_APPS not in entry.options


async def test_options_settings_classic_fills_port(hass: HomeAssistant) -> None:
    entry = make_entry({CONF_ENABLE_ADB: False})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "enable_ime": True,
            CONF_ENABLE_ADB: True,
            CONF_ADB_MODE: ADB_MODE_CLASSIC,
            "keepalive_interval": 60,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ADB_PORT] == 5555
    assert entry.options[CONF_ADB_MODE] == ADB_MODE_CLASSIC


async def test_options_adb_pair_reachable_and_switches_to_tls(
    hass: HomeAssistant,
) -> None:
    entry = make_entry({CONF_ENABLE_ADB: False})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "adb_pair"}
    )
    assert result["step_id"] == "adb_pair"
    adb = MagicMock()
    adb.pair_wireless.return_value = True
    with patch(
        "custom_components.tcl_android_tv_remote.config_flow.create_adb",
        return_value=adb,
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"pairing_port": 41745, "pairing_code": "123456", "connect_port": 44491},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ADB_MODE] == ADB_MODE_TLS
    assert entry.options[CONF_ADB_PORT] == 44491
    assert entry.options[CONF_ENABLE_ADB] is True


async def test_reauth_flow(hass: HomeAssistant, mock_api) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pair"
    mock_api.async_start_pairing.assert_awaited()

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pin": "123456"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"


async def test_reauth_wrong_pin_stays_on_pair(hass: HomeAssistant, mock_api) -> None:
    from androidtvremote2 import InvalidAuth

    entry = make_entry()
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    mock_api.async_finish_pairing.side_effect = InvalidAuth
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pin": "000000"}
    )
    assert result["step_id"] == "pair"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_updates_host(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.20"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.0.2.20"


async def test_reconfigure_rejects_different_tv(hass: HomeAssistant, mock_api) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    mock_api.async_get_name_and_mac.return_value = ("Other TV", "AA:BB:CC:DD:EE:FF")
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.30"}
    )
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data[CONF_HOST] == HOST


async def test_user_flow_cannot_connect(hass: HomeAssistant, mock_api) -> None:
    from androidtvremote2 import CannotConnect

    mock_api.async_get_name_and_mac.side_effect = CannotConnect
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}
