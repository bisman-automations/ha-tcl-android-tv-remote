"""Setup, entity, service and coordinator tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.tcl_android_tv_remote.adb import AdbClient, HdmiSource
from custom_components.tcl_android_tv_remote.const import (
    ADB_MODE_TLS,
    CONF_ADB_MODE,
    CONF_ADB_PORT,
    CONF_ENABLE_ADB,
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .conftest import CLASSIC_OPTIONS, make_entry

pytestmark = pytest.mark.usefixtures("mock_api")

MEDIA_PLAYER = "media_player.tcl_living_room"
SELECT = "select.tcl_living_room_source"


def _fake_adb(
    *, use_tls: bool = False, port: int = 5555, alive: bool = True
) -> MagicMock:
    adb = MagicMock(spec=AdbClient)
    adb.host = "192.0.2.10"
    adb.port = port
    adb.use_tls = use_tls
    adb.available = alive
    adb.status = "connected" if alive else "offline"
    adb.last_error = None if alive else "ConnectionError: refused"
    adb.keep_alive_tick.return_value = alive
    adb.ensure_connected.return_value = alive
    adb.hdmi_sources = [
        HdmiSource("Apple TV", "com.tcl.tvinput/.TvPassThroughService/HW15", 1),
        HdmiSource("HDMI 2", "com.tcl.tvinput/.TvPassThroughService/HW16", 2),
    ]
    adb.active_input = "com.tcl.tvinput/.TvPassThroughService/HW15"
    adb.current_source_name.return_value = "Apple TV" if alive else None
    adb.media = None
    adb.select_hdmi_by_name.return_value = True
    adb.shell.return_value = "output"
    return adb


async def _setup(hass: HomeAssistant, entry, adb: MagicMock | None = None):
    entry.add_to_hass(hass)
    with patch(
        "custom_components.tcl_android_tv_remote.create_adb",
        return_value=adb or _fake_adb(),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_setup_without_adb(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    ent_reg = er.async_get(hass)
    platforms = sorted(
        e.domain for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    )
    # No ADB: no ADB sensors and no ADB-backed buttons
    assert platforms == ["button", "media_player", "remote", "select"]


async def test_setup_with_adb_sources(hass: HomeAssistant, mock_api) -> None:
    entry = make_entry(CLASSIC_OPTIONS)
    adb = _fake_adb()
    await _setup(hass, entry, adb)

    state = hass.states.get(MEDIA_PLAYER)
    assert state.attributes["source_list"] == ["Apple TV", "HDMI 2"]
    assert state.attributes["source"] == "Apple TV"
    assert hass.states.get(SELECT).state == "Apple TV"
    assert hass.states.get("binary_sensor.tcl_living_room_adb").state == "on"

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT, "option": "HDMI 2"},
        blocking=True,
    )
    adb.select_hdmi_by_name.assert_called_with("HDMI 2")

    # Apps go over the remote protocol, on the event loop
    await hass.services.async_call(
        "media_player",
        "select_source",
        {"entity_id": MEDIA_PLAYER, "source": "com.netflix.ninja"},
        blocking=True,
    )
    mock_api.send_launch_app_command.assert_called_with("com.netflix.ninja")


async def test_hdmi_switch_failure_raises(hass: HomeAssistant) -> None:
    entry = make_entry(CLASSIC_OPTIONS)
    adb = _fake_adb()
    adb.select_hdmi_by_name.return_value = False
    await _setup(hass, entry, adb)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": SELECT, "option": "HDMI 2"},
            blocking=True,
        )


async def test_playing_state_ignored_when_off(hass: HomeAssistant, mock_api) -> None:
    entry = make_entry(CLASSIC_OPTIONS)
    adb = _fake_adb()
    adb.media = MagicMock(
        playback_state="playing", title="x", artist=None, album=None, image_url=None
    )
    mock_api.is_on = False
    await _setup(hass, entry, adb)
    assert hass.states.get(MEDIA_PLAYER).state == "off"


async def test_adb_offline_raises_one_repair_issue(hass: HomeAssistant) -> None:
    entry = make_entry(CLASSIC_OPTIONS)
    await _setup(hass, entry, _fake_adb(alive=False))
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"adb_offline_{entry.entry_id}")
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.translation_key == "adb_offline_classic"
    assert hass.states.get("binary_sensor.tcl_living_room_adb").state == "off"


async def test_tls_port_rediscovered_and_saved(hass: HomeAssistant) -> None:
    entry = make_entry(
        {CONF_ENABLE_ADB: True, CONF_ADB_MODE: ADB_MODE_TLS, CONF_ADB_PORT: 40000}
    )
    adb = _fake_adb(use_tls=True, port=40000)
    # Old port dead; works once the coordinator moves to the new one
    adb.keep_alive_tick.side_effect = lambda: adb.port == 41111
    with patch(
        "custom_components.tcl_android_tv_remote.coordinator.discover_connect_port",
        AsyncMock(return_value=41111),
    ):
        await _setup(hass, entry, adb)
    assert adb.port == 41111
    assert entry.options[CONF_ADB_PORT] == 41111
    assert hass.states.get("binary_sensor.tcl_living_room_adb").state == "on"
    assert entry.state is ConfigEntryState.LOADED


async def test_adb_command_requires_target_and_returns_output(
    hass: HomeAssistant,
) -> None:
    entry = make_entry(CLASSIC_OPTIONS)
    await _setup(hass, entry)

    # Untargeted calls are rejected by the schema (never "all TVs")
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "adb_command",
            {"command": "echo hi"},
            blocking=True,
            return_response=True,
        )

    response = await hass.services.async_call(
        DOMAIN,
        "adb_command",
        {"entity_id": MEDIA_PLAYER, "command": "echo hi"},
        blocking=True,
        return_response=True,
    )
    assert response == {"results": {"TCL Living Room": "output"}}


async def test_refresh_hdmi_without_adb_errors(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "refresh_hdmi", {"entity_id": MEDIA_PLAYER}, blocking=True
        )


async def test_unload(hass: HomeAssistant) -> None:
    entry = make_entry(CLASSIC_OPTIONS)
    adb = _fake_adb()
    await _setup(hass, entry, adb)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    adb.close.assert_called()


async def test_diagnostics_redacts_host(hass: HomeAssistant) -> None:
    from custom_components.tcl_android_tv_remote.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = make_entry(CLASSIC_OPTIONS)
    await _setup(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["config_entry_data"]["host"] == "**REDACTED**"
    assert diag["adb"]["available"] is True
    assert [s["name"] for s in diag["adb"]["hdmi_sources"]] == ["Apple TV", "HDMI 2"]
    assert diag["source_list"] == ["Apple TV", "HDMI 2"]


async def test_migration_removes_old_options(hass: HomeAssistant) -> None:
    entry = make_entry(
        {
            **{k: v for k, v in CLASSIC_OPTIONS.items() if k != CONF_ADB_MODE},
            "adb_port": 44491,
            "allowed_sources": ["Apple TV"],
            "enforce_allowed": True,
        }
    )
    await _setup(hass, entry)
    assert entry.minor_version == 2
    assert "allowed_sources" not in entry.options
    assert "enforce_allowed" not in entry.options
    # The mode that used to be inferred from the port is now stored
    assert entry.options[CONF_ADB_MODE] == ADB_MODE_TLS
    assert entry.state is ConfigEntryState.LOADED


async def test_migration_leaves_adb_off_entries_alone(hass: HomeAssistant) -> None:
    entry = make_entry({CONF_ENABLE_ADB: False, "enforce_allowed": False})
    await _setup(hass, entry)
    assert entry.options == {CONF_ENABLE_ADB: False}
    assert entry.minor_version == 2


async def test_channel_entry(hass: HomeAssistant, mock_api) -> None:
    """Typing a channel sends each digit; a newer number replaces one in progress."""
    entry = make_entry()
    await _setup(hass, entry)
    play = {
        "entity_id": MEDIA_PLAYER,
        "media_content_type": "channel",
    }
    with patch(
        "custom_components.tcl_android_tv_remote.media_player.asyncio.sleep",
        AsyncMock(),
    ):
        await hass.services.async_call(
            "media_player",
            "play_media",
            {**play, "media_content_id": "45"},
            blocking=True,
        )
    sent = [c.args[0] for c in mock_api.send_key_command.call_args_list]
    assert sent == ["4", "5"]

    # A second number while the first is still being typed: the first stops,
    # and its action still finishes without an error.
    mock_api.send_key_command.reset_mock()
    first = hass.async_create_task(
        hass.services.async_call(
            "media_player",
            "play_media",
            {**play, "media_content_id": "1234"},
            blocking=True,
        )
    )
    await asyncio.sleep(0.15)  # "1" and "2" are typed by now
    await hass.services.async_call(
        "media_player", "play_media", {**play, "media_content_id": "7"}, blocking=True
    )
    await first
    sent = [c.args[0] for c in mock_api.send_key_command.call_args_list]
    assert sent[-1] == "7"
    assert len(sent) < 5

    # Unloading stops a number that's still being typed.
    started = hass.async_create_task(
        hass.services.async_call(
            "media_player",
            "play_media",
            {**play, "media_content_id": "999999"},
            blocking=True,
        )
    )
    await asyncio.sleep(0)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await started
