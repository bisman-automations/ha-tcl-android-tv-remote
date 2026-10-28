"""Rebuild, remove and options-flow tests for saved HDMI inputs."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_components.tcl_android_tv_remote.adb import HdmiSource
from custom_components.tcl_android_tv_remote.const import (
    CONF_APP_ICON,
    CONF_APP_NAME,
    CONF_APPS,
    CONF_HDMI_INPUTS,
    CONF_HDMI_REMOVED,
    DOMAIN,
)
from custom_components.tcl_android_tv_remote.sources import (
    hdmi_entity_unique_id,
    match_hdmi_tokens,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import CLASSIC_OPTIONS, make_entry
from .test_init import MEDIA_PLAYER, SELECT, _fake_adb, _setup

pytestmark = pytest.mark.usefixtures("mock_api")

HW15 = "com.tcl.tvinput/.TvPassThroughService/HW15"
HW16 = "com.tcl.tvinput/.TvPassThroughService/HW16"
HW18 = "com.tcl.tvinput/.TvPassThroughService/HW18"


def _source_list(hass: HomeAssistant) -> list[str]:
    state = hass.states.get(MEDIA_PLAYER)
    assert state is not None
    return list(state.attributes["source_list"])


def _select_options(hass: HomeAssistant) -> list[str]:
    state = hass.states.get(SELECT)
    assert state is not None
    return list(state.attributes["options"])


def _apps_options() -> dict:
    return {
        **CLASSIC_OPTIONS,
        CONF_APPS: {"com.plexapp.android": {CONF_APP_NAME: "Plex", CONF_APP_ICON: ""}},
    }


def test_match_hdmi_tokens_by_id_name_and_port() -> None:
    sources = [
        HdmiSource("Apple TV", HW15, 1, "Apple TV"),
        HdmiSource("HDMI 2", HW16, 2),
    ]
    matched, unknown, ambiguous = match_hdmi_tokens(
        sources, ["HW16", "hdmi 1", "Apple TV", "nope"]
    )
    assert unknown == ["nope"]
    assert ambiguous == []
    assert {source.input_id for source in matched} == {HW15, HW16}

    ambiguous_sources = [
        HdmiSource("Apple TV 4K", HW15, 1),
        HdmiSource("Apple TV Lite", HW16, 2),
    ]
    matched, unknown, ambiguous = match_hdmi_tokens(ambiguous_sources, ["Apple"])
    assert matched == []
    assert unknown == []
    assert ambiguous == ["Apple"]


async def _remove(hass: HomeAssistant, inputs: list[str]) -> None:
    await hass.services.async_call(
        DOMAIN,
        "remove_hdmi_inputs",
        {"entity_id": MEDIA_PLAYER, "inputs": inputs},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_remove_one_input_updates_lists_and_purges_orphan(
    hass: HomeAssistant,
) -> None:
    entry = make_entry(_apps_options())
    adb = _fake_adb()
    await _setup(hass, entry, adb)
    assert _source_list(hass) == ["Apple TV", "HDMI 2", "Plex"]

    registry = er.async_get(hass)
    assert entry.unique_id
    stale_id = hdmi_entity_unique_id(entry.unique_id, HW16)
    kept_id = hdmi_entity_unique_id(entry.unique_id, HW15)
    registry.async_get_or_create(
        "sensor", DOMAIN, stale_id, config_entry=entry, original_name="Old HDMI 2"
    )
    registry.async_get_or_create(
        "sensor", DOMAIN, kept_id, config_entry=entry, original_name="Apple TV input"
    )

    await _remove(hass, ["HDMI 2"])

    assert _source_list(hass) == ["Apple TV", "Plex"]
    assert _select_options(hass) == ["Apple TV", "Plex"]
    assert HW16 in entry.options[CONF_HDMI_REMOVED]
    assert HW16 not in entry.options[CONF_HDMI_INPUTS]
    assert registry.async_get_entity_id("sensor", DOMAIN, stale_id) is None
    assert registry.async_get_entity_id("sensor", DOMAIN, kept_id) is not None
    assert registry.async_get(SELECT) is not None
    assert registry.async_get(MEDIA_PLAYER) is not None

    # The keep-alive poll must not put a removed input back.
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert "HDMI 2" not in _source_list(hass)

    # Refresh HDMI adds back what the TV still reports.
    await hass.services.async_call(
        DOMAIN, "refresh_hdmi", {"entity_id": MEDIA_PLAYER}, blocking=True
    )
    await hass.async_block_till_done()
    assert _source_list(hass) == ["Apple TV", "HDMI 2", "Plex"]
    assert entry.options[CONF_HDMI_REMOVED] == []


async def test_remove_several_inputs_by_id_and_name(hass: HomeAssistant) -> None:
    entry = make_entry(_apps_options())
    await _setup(hass, entry, _fake_adb())

    await _remove(hass, ["Apple TV", HW16])

    assert _source_list(hass) == ["Plex"]
    assert _select_options(hass) == ["Plex"]
    assert set(entry.options[CONF_HDMI_REMOVED]) == {HW15, HW16}
    assert entry.options[CONF_APPS]["com.plexapp.android"][CONF_APP_NAME] == "Plex"


async def test_remove_unknown_input_leaves_the_list_alone(hass: HomeAssistant) -> None:
    entry = make_entry(CLASSIC_OPTIONS)
    await _setup(hass, entry, _fake_adb())
    with pytest.raises(ServiceValidationError):
        await _remove(hass, ["Blu-ray"])
    assert _source_list(hass) == ["Apple TV", "HDMI 2"]
    assert CONF_HDMI_INPUTS not in entry.options


async def test_rebuild_without_adb_errors(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "rebuild_sources", {"entity_id": MEDIA_PLAYER}, blocking=True
        )


async def test_rebuild_sources_forgets_saved_inputs_and_custom_names(
    hass: HomeAssistant,
) -> None:
    entry = make_entry(
        {
            **_apps_options(),
            CONF_HDMI_INPUTS: {
                HW15: {
                    "name": "Old Apple TV",
                    "port": 1,
                    "custom_name": "Old Apple TV",
                },
                HW18: {
                    "name": "Unplugged Disc",
                    "port": 4,
                    "custom_name": "Unplugged Disc",
                },
            },
            CONF_HDMI_REMOVED: [],
        }
    )
    adb = _fake_adb()
    discovered = [
        [
            HdmiSource("HDMI 1", HW15, 1),
            HdmiSource("Soundbar", HW16, 2, "Soundbar"),
        ],
        [HdmiSource("HDMI 1", HW15, 1)],
    ]

    def rebuild() -> bool:
        adb.hdmi_sources = discovered.pop(0)
        adb.custom_labels = {}
        return True

    adb.rebuild_hdmi_sources.side_effect = rebuild
    await _setup(hass, entry, adb)

    # A poll keeps a saved input the TV did not report. That is the stale port.
    assert "Unplugged Disc" in _source_list(hass)
    assert entry.options[CONF_HDMI_INPUTS][HW15]["custom_name"] == "Old Apple TV"

    registry = er.async_get(hass)
    assert entry.unique_id
    button_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.unique_id}_btn_rebuild_sources"
    )
    assert button_id is not None
    button = registry.async_get(button_id)
    assert button is not None
    assert button.entity_category is EntityCategory.CONFIG

    await hass.services.async_call(
        "button", "press", {"entity_id": button_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert _source_list(hass) == ["HDMI 1", "Soundbar", "Plex"]
    assert _select_options(hass) == ["HDMI 1", "Soundbar", "Plex"]
    stored = entry.options[CONF_HDMI_INPUTS]
    assert set(stored) == {HW15, HW16}
    assert "custom_name" not in stored[HW15]
    assert "custom_name" not in stored[HW16]
    assert entry.options[CONF_HDMI_REMOVED] == []
    adb.rebuild_hdmi_sources.assert_called_once()

    # The action takes the same path.
    adb.rebuild_hdmi_sources.reset_mock()
    adb.hdmi_sources = [HdmiSource("HDMI 1", HW15, 1)]
    await hass.services.async_call(
        DOMAIN, "rebuild_sources", {"entity_id": MEDIA_PLAYER}, blocking=True
    )
    await hass.async_block_till_done()
    assert _source_list(hass) == ["HDMI 1", "Plex"]
    adb.rebuild_hdmi_sources.assert_called_once()


async def test_rebuild_still_clears_the_list_when_tv_names_cannot(
    hass: HomeAssistant,
) -> None:
    entry = make_entry(
        {
            **CLASSIC_OPTIONS,
            CONF_HDMI_INPUTS: {HW18: {"name": "Unplugged Disc", "port": 4}},
            CONF_HDMI_REMOVED: [],
        }
    )
    adb = _fake_adb()

    def rebuild() -> bool:
        adb.hdmi_sources = [HdmiSource("HDMI 1", HW15, 1)]
        adb.custom_labels = {}
        adb.last_error = "permission denied"
        return False

    adb.rebuild_hdmi_sources.side_effect = rebuild
    await _setup(hass, entry, adb)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "rebuild_sources", {"entity_id": MEDIA_PLAYER}, blocking=True
        )
    await hass.async_block_till_done()
    assert "Unplugged Disc" not in _source_list(hass)
    assert _source_list(hass) == ["HDMI 1"]


async def _open_hdmi_options(hass: HomeAssistant, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert "hdmi_inputs" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "hdmi_inputs"}
    )
    assert result["step_id"] == "hdmi_inputs"
    return result


async def test_options_flow_removes_selected_inputs(hass: HomeAssistant) -> None:
    entry = make_entry(_apps_options())
    adb = _fake_adb()
    entry.add_to_hass(hass)
    # Hold the ADB patch across the options-flow reload.
    with patch("custom_components.tcl_android_tv_remote.create_adb", return_value=adb):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        result = await _open_hdmi_options(hass, entry)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"hdmi_remove": [HW15, HW16]}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

    assert _source_list(hass) == ["Plex"]
    assert _select_options(hass) == ["Plex"]
    assert set(entry.options[CONF_HDMI_REMOVED]) == {HW15, HW16}


async def test_options_flow_rebuild_ignores_the_selection(hass: HomeAssistant) -> None:
    entry = make_entry(
        {
            **_apps_options(),
            CONF_HDMI_INPUTS: {
                HW18: {"name": "Unplugged Disc", "port": 4, "custom_name": "Disc"},
            },
            CONF_HDMI_REMOVED: [HW15],
        }
    )
    adb = _fake_adb()

    def rebuild() -> bool:
        adb.hdmi_sources = [
            HdmiSource("HDMI 1", HW15, 1),
            HdmiSource("HDMI 2", HW16, 2),
        ]
        adb.custom_labels = {}
        return True

    adb.rebuild_hdmi_sources.side_effect = rebuild
    entry.add_to_hass(hass)
    with patch("custom_components.tcl_android_tv_remote.create_adb", return_value=adb):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert "Unplugged Disc" in _source_list(hass)

        result = await _open_hdmi_options(hass, entry)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"hdmi_remove": [HW18], "rebuild_sources": True},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

    assert "Unplugged Disc" not in _source_list(hass)
    assert _source_list(hass) == ["HDMI 1", "HDMI 2", "Plex"]
    assert entry.options[CONF_HDMI_REMOVED] == []
    assert "custom_name" not in entry.options[CONF_HDMI_INPUTS][HW15]
