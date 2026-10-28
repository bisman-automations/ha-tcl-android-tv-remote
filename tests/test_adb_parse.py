"""Unit tests for HDMI / CEC / media parsing and HDMI name matching."""

from __future__ import annotations

from unittest.mock import patch

from custom_components.tcl_android_tv_remote.adb import (
    CUSTOM_LABELS_SETTING,
    AdbClient,
    HdmiSource,
    extract_active_tv_input,
    extract_hdmi_sources,
    extract_media_metadata,
    format_custom_labels,
    parse_custom_labels,
)

# Trimmed `dumpsys tv_input` in the shape TCL Google TV firmware produces
TCL_DUMPSYS = """
mHardwareList:
  TvInputHardwareInfo {id=15, type=9, audio_type=0, audio_addr=, hdmi_port=1}
  TvInputHardwareInfo {id=16, type=9, audio_type=0, audio_addr=, hdmi_port=2}
  TvInputHardwareInfo {id=17, type=9, audio_type=0, audio_addr=, hdmi_port=3}
mHardwareInputIdMap:
  15: com.tcl.tvinput/.TvPassThroughService/HW15
  16: com.tcl.tvinput/.TvPassThroughService/HW16
  17: com.tcl.tvinput/.TvPassThroughService/HW17
  2: com.tcl.tvinput/.TvPassThroughService/HDMI30004
CEC: device display_name: PlayStation 5 power_status: on port_id: 2
inputId: com.tcl.tvinput/.TvPassThroughService/HW16
"""

CUSTOM_LABELS = (
    "com.tcl.tvinput%2F.TvPassThroughService%2FHW15,Apple%20TV:"
    "com.tcl.tvinput%2F.TvPassThroughService%2FHW17,Game%3A%20Switch"
)

MEDIA = """
MediaSession
  metadata: size=3, description=Stranger Things, S1, Netflix
    android.media.metadata.TITLE: Stranger Things
    android.media.metadata.ARTIST: Netflix
  state=PlaybackState {state=3, position=1000}
"""


def test_parse_custom_labels_decodes_everything() -> None:
    labels = parse_custom_labels(CUSTOM_LABELS)
    assert labels == {
        "com.tcl.tvinput/.TvPassThroughService/HW15": "Apple TV",
        # ":" inside a label arrives encoded and must survive the split
        "com.tcl.tvinput/.TvPassThroughService/HW17": "Game: Switch",
    }
    assert parse_custom_labels("null") == {}
    assert parse_custom_labels(None) == {}


def test_extract_active_input() -> None:
    assert (
        extract_active_tv_input(TCL_DUMPSYS)
        == "com.tcl.tvinput/.TvPassThroughService/HW16"
    )


def test_extract_hdmi_sources_prefers_custom_then_cec() -> None:
    sources = extract_hdmi_sources(TCL_DUMPSYS, parse_custom_labels(CUSTOM_LABELS))
    by_port = {s.port: s.name for s in sources}
    assert by_port == {1: "Apple TV", 2: "HDMI 2 - PlayStation 5", 3: "Game: Switch"}
    # HDMI30004-style dumpsys noise is dropped
    assert all("30004" not in s.input_id for s in sources)


def test_extract_hdmi_sources_without_labels_uses_ports() -> None:
    names = [s.name for s in extract_hdmi_sources(TCL_DUMPSYS)]
    assert names == ["HDMI 1", "HDMI 2 - PlayStation 5", "HDMI 3"]


def test_media_metadata() -> None:
    meta = extract_media_metadata(MEDIA)
    assert meta is not None
    assert meta.title == "Stranger Things"
    assert meta.artist == "Netflix"
    assert meta.playback_state == "playing"
    assert extract_media_metadata("") is None


def _client_with(sources: list[HdmiSource]) -> AdbClient:
    client = AdbClient("192.0.2.10")
    client._hdmi_sources = sources  # noqa: SLF001
    return client


def test_find_hdmi_exact_beats_partial() -> None:
    client = _client_with(
        [
            HdmiSource("Apple TV 4K", "x/HW15", 1),
            HdmiSource("Apple TV", "x/HW16", 2),
        ]
    )
    assert client.find_hdmi_source("Apple TV").port == 2
    assert client.find_hdmi_source("apple tv 4k").port == 1
    assert client.find_hdmi_source("HDMI 1").port == 1


def test_find_hdmi_ambiguous_partial_is_not_guessed() -> None:
    client = _client_with(
        [
            HdmiSource("Apple TV 4K", "x/HW15", 1),
            HdmiSource("Apple TV Lite", "x/HW16", 2),
        ]
    )
    assert client.find_hdmi_source("Apple") is None
    assert client.find_hdmi_source("Lite").port == 2


def test_find_hdmi_synthesizes_tcl_mapping_when_empty() -> None:
    client = _client_with([])
    with patch.object(client, "refresh_hdmi", return_value=[]):
        src = client.find_hdmi_source("hdmi3")
    assert src is not None
    assert src.input_id.endswith("/HW17")


def test_connect_with_unknown_port_fails_fast() -> None:
    client = AdbClient("192.0.2.10", port=0, use_tls=True)
    assert client.ensure_connected() is False
    assert client.status == "offline"


def test_custom_labels_roundtrip() -> None:
    labels = parse_custom_labels(CUSTOM_LABELS)
    assert parse_custom_labels(format_custom_labels(labels)) == labels


def test_rebuild_clears_custom_labels_then_rediscovers() -> None:
    """Rebuild deletes the TV's custom names before parsing dumpsys again."""
    client = AdbClient("192.0.2.10")
    client._adb = object()  # noqa: SLF001
    client._status = "connected"  # noqa: SLF001
    stale_id = "com.tcl.tvinput/.TvPassThroughService/HW15"
    client._hdmi_sources = [HdmiSource("Old Blu-ray", stale_id, 1, "Old Blu-ray")]  # noqa: SLF001
    client._custom_labels = {stale_id: "Old Blu-ray"}  # noqa: SLF001
    calls: list[str] = []

    def shell(command: str) -> str:
        calls.append(command)
        if command.startswith("echo"):
            return "ok"
        if command.startswith("settings get"):
            return "null"
        if command.startswith("dumpsys tv_input"):
            return TCL_DUMPSYS
        return ""

    with patch.object(client, "shell", side_effect=shell):
        assert client.rebuild_hdmi_sources() is True

    assert f"settings delete secure {CUSTOM_LABELS_SETTING}" in calls
    assert client.custom_labels == {}
    names = [source.name for source in client.hdmi_sources]
    assert "Old Blu-ray" not in names
    assert names == ["HDMI 1", "HDMI 2 - PlayStation 5", "HDMI 3"]


def test_remove_hdmi_inputs_rewrites_remaining_custom_label() -> None:
    client = AdbClient("192.0.2.10")
    client._adb = object()  # noqa: SLF001
    kept = "com.tcl.tvinput/.TvPassThroughService/HW17"
    dropped = "com.tcl.tvinput/.TvPassThroughService/HW15"
    client._hdmi_sources = [  # noqa: SLF001
        HdmiSource("Apple TV", dropped, 1, "Apple TV"),
        HdmiSource("Game: Switch", kept, 3, "Game: Switch"),
    ]
    client._custom_labels = {dropped: "Apple TV", kept: "Game: Switch"}  # noqa: SLF001
    calls: list[str] = []

    def shell(command: str) -> str:
        calls.append(command)
        return ""

    with (
        patch.object(client, "shell", side_effect=shell),
        patch.object(client, "ensure_connected", return_value=True),
    ):
        assert client.remove_hdmi_inputs({dropped}) is True

    assert [source.input_id for source in client.hdmi_sources] == [kept]
    assert client.custom_labels == {kept: "Game: Switch"}
    put = next(command for command in calls if command.startswith("settings put"))
    payload = put.split("'", 1)[1].removesuffix("'")
    assert parse_custom_labels(payload) == {kept: "Game: Switch"}

    calls.clear()
    with (
        patch.object(client, "shell", side_effect=shell),
        patch.object(client, "ensure_connected", return_value=True),
    ):
        assert client.remove_hdmi_inputs({kept}) is True
    assert client.hdmi_sources == []
    assert client.custom_labels == {}
    assert f"settings delete secure {CUSTOM_LABELS_SETTING}" in calls
