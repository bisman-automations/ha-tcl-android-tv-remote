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


def _connected_client() -> AdbClient:
    client = AdbClient("192.0.2.10")
    client._adb = object()  # noqa: SLF001
    client._status = "connected"  # noqa: SLF001
    return client


def _put_payload(command: str) -> dict[str, str]:
    payload = command.split("'", 1)[1].removesuffix("'")
    return parse_custom_labels(payload)


def test_rebuild_clears_custom_labels_then_rediscovers() -> None:
    """Rebuild reads the names, deletes them, then parses dumpsys again."""
    client = _connected_client()
    stale_id = "com.tcl.tvinput/.TvPassThroughService/HW15"
    client._hdmi_sources = [HdmiSource("Old Blu-ray", stale_id, 1, "Old Blu-ray")]  # noqa: SLF001
    client._custom_labels = {stale_id: "Old Blu-ray"}  # noqa: SLF001
    calls: list[str] = []
    gets = 0

    def shell(command: str) -> str:
        nonlocal gets
        calls.append(command)
        if command.startswith("echo"):
            return "ok"
        if command.startswith("settings get"):
            gets += 1
            # The clear reads the names that are actually on the TV. The
            # refresh afterwards sees the setting gone.
            return CUSTOM_LABELS if gets == 1 else "null"
        if command.startswith("dumpsys tv_input"):
            return TCL_DUMPSYS
        return ""

    with patch.object(client, "shell", side_effect=shell):
        assert client.rebuild_hdmi_sources() is True

    assert calls.index(f"settings get secure {CUSTOM_LABELS_SETTING}") < calls.index(
        f"settings delete secure {CUSTOM_LABELS_SETTING}"
    )
    assert client.custom_labels == {}
    names = [source.name for source in client.hdmi_sources]
    assert "Old Blu-ray" not in names
    assert names == ["HDMI 1", "HDMI 2 - PlayStation 5", "HDMI 3"]


def test_rebuild_does_not_delete_when_the_setting_is_already_empty() -> None:
    client = _connected_client()
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

    assert f"settings delete secure {CUSTOM_LABELS_SETTING}" not in calls
    assert not any(command.startswith("settings put") for command in calls)
    assert client.custom_labels == {}


def test_rebuild_skips_delete_when_the_read_fails() -> None:
    """Standby: the read fails, so rebuild must not wipe the names."""
    client = _connected_client()
    stale_id = "com.tcl.tvinput/.TvPassThroughService/HW15"
    client._custom_labels = {stale_id: "Old Blu-ray"}  # noqa: SLF001
    calls: list[str] = []

    def shell(command: str) -> str | None:
        calls.append(command)
        if command.startswith("echo"):
            return "ok"
        if command.startswith("settings get"):
            return None
        if command.startswith("dumpsys tv_input"):
            return TCL_DUMPSYS
        return ""

    with patch.object(client, "shell", side_effect=shell):
        assert client.rebuild_hdmi_sources() is False

    assert f"settings delete secure {CUSTOM_LABELS_SETTING}" not in calls
    assert not any(command.startswith("settings put") for command in calls)
    assert client.custom_labels == {stale_id: "Old Blu-ray"}


def test_remove_hdmi_inputs_keeps_tv_side_renames_and_other_ids() -> None:
    """The write is the fresh TV copy minus only the requested ids."""
    client = _connected_client()
    kept = "com.tcl.tvinput/.TvPassThroughService/HW17"
    dropped = "com.tcl.tvinput/.TvPassThroughService/HW15"
    extra = "com.tcl.tvinput/.TvPassThroughService/HW16"
    client._hdmi_sources = [  # noqa: SLF001
        HdmiSource("Apple TV", dropped, 1, "Apple TV"),
        HdmiSource("Game: Switch", kept, 3, "Game: Switch"),
    ]
    # Cache is stale: the TV has since renamed the kept input and added one.
    client._custom_labels = {dropped: "Apple TV", kept: "Game: Switch"}  # noqa: SLF001
    on_tv = {
        dropped: "Apple TV",
        kept: "Switch OLED",
        extra: "Blu-ray",
    }
    calls: list[str] = []

    def shell(command: str) -> str:
        calls.append(command)
        if command.startswith("settings get"):
            return format_custom_labels(on_tv)
        return ""

    with (
        patch.object(client, "shell", side_effect=shell),
        patch.object(client, "ensure_connected", return_value=True),
    ):
        assert client.remove_hdmi_inputs({dropped}) is True

    assert [source.input_id for source in client.hdmi_sources] == [kept]
    assert client.custom_labels == {kept: "Switch OLED", extra: "Blu-ray"}
    puts = [command for command in calls if command.startswith("settings put")]
    assert len(puts) == 1
    assert _put_payload(puts[0]) == {kept: "Switch OLED", extra: "Blu-ray"}
    assert f"settings delete secure {CUSTOM_LABELS_SETTING}" not in calls


def test_remove_hdmi_inputs_skips_write_when_the_read_fails() -> None:
    """After a restart the cache is empty. A failed read must not write it."""
    client = _connected_client()
    kept = "com.tcl.tvinput/.TvPassThroughService/HW17"
    dropped = "com.tcl.tvinput/.TvPassThroughService/HW15"
    client._hdmi_sources = [  # noqa: SLF001
        HdmiSource("Apple TV", dropped, 1, "Apple TV"),
        HdmiSource("Game: Switch", kept, 3, "Game: Switch"),
    ]
    client._custom_labels = {}  # noqa: SLF001
    calls: list[str] = []

    def shell(command: str) -> str | None:
        calls.append(command)
        if command.startswith("settings get"):
            return None
        return ""

    with (
        patch.object(client, "shell", side_effect=shell),
        patch.object(client, "ensure_connected", return_value=True),
    ):
        assert client.remove_hdmi_inputs({dropped}) is False

    assert any(command.startswith("settings get") for command in calls)
    assert not any(command.startswith("settings put") for command in calls)
    assert f"settings delete secure {CUSTOM_LABELS_SETTING}" not in calls
    assert client.custom_labels == {}
    # Home Assistant can still hide the input the user asked to remove.
    assert [source.input_id for source in client.hdmi_sources] == [kept]
    assert client.last_error == (
        "Could not read custom HDMI names from the TV; they were left unchanged"
    )


def test_remove_hdmi_inputs_deletes_only_when_the_last_name_is_removed() -> None:
    client = _connected_client()
    kept = "com.tcl.tvinput/.TvPassThroughService/HW17"
    dropped = "com.tcl.tvinput/.TvPassThroughService/HW15"
    client._hdmi_sources = [HdmiSource("Apple TV", dropped, 1, "Apple TV")]  # noqa: SLF001
    calls: list[str] = []
    on_tv = {dropped: "Apple TV"}

    def shell(command: str) -> str:
        calls.append(command)
        if command.startswith("settings get"):
            return format_custom_labels(on_tv) if on_tv else "null"
        if command.startswith("settings delete"):
            on_tv.clear()
            return ""
        return ""

    with (
        patch.object(client, "shell", side_effect=shell),
        patch.object(client, "ensure_connected", return_value=True),
    ):
        assert client.remove_hdmi_inputs({dropped}) is True

    assert client.hdmi_sources == []
    assert client.custom_labels == {}
    assert f"settings delete secure {CUSTOM_LABELS_SETTING}" in calls
    assert not any(
        command.startswith("settings put") and not command.endswith(" null")
        for command in calls
    )

    # Removing an input when the fresh read is already empty must not delete.
    calls.clear()
    client._hdmi_sources = [HdmiSource("HDMI 3", kept, 3)]  # noqa: SLF001
    with (
        patch.object(client, "shell", side_effect=shell),
        patch.object(client, "ensure_connected", return_value=True),
    ):
        assert client.remove_hdmi_inputs({kept}) is True
    assert f"settings delete secure {CUSTOM_LABELS_SETTING}" not in calls
    assert not any(command.startswith("settings put") for command in calls)


def test_remove_hdmi_inputs_unreadable_text_is_not_an_empty_setting() -> None:
    """Permission text must not be parsed as 'no names' and then deleted."""
    client = _connected_client()
    dropped = "com.tcl.tvinput/.TvPassThroughService/HW15"
    calls: list[str] = []

    def shell(command: str) -> str:
        calls.append(command)
        if command.startswith("settings get"):
            return "java.lang.SecurityException: permission denied"
        return ""

    with (
        patch.object(client, "shell", side_effect=shell),
        patch.object(client, "ensure_connected", return_value=True),
    ):
        assert client.remove_hdmi_inputs({dropped}) is False

    assert f"settings delete secure {CUSTOM_LABELS_SETTING}" not in calls
    assert not any(command.startswith("settings put") for command in calls)


def test_rename_one_label_preserves_the_fresh_copy() -> None:
    """Add/rename goes through the same read-then-edit path as remove."""
    client = _connected_client()
    kept = "com.tcl.tvinput/.TvPassThroughService/HW17"
    renamed = "com.tcl.tvinput/.TvPassThroughService/HW15"
    client._custom_labels = {renamed: "Stale Apple TV"}  # noqa: SLF001
    on_tv = {renamed: "Apple TV", kept: "Switch OLED"}
    calls: list[str] = []

    def shell(command: str) -> str:
        calls.append(command)
        if command.startswith("settings get"):
            return format_custom_labels(on_tv)
        return ""

    def rename(labels: dict[str, str]) -> None:
        labels[renamed] = "Living Room Apple TV"

    with (
        patch.object(client, "shell", side_effect=shell),
        patch.object(client, "ensure_connected", return_value=True),
    ):
        assert client._apply_custom_label_edit(rename) is True  # noqa: SLF001

    puts = [command for command in calls if command.startswith("settings put")]
    assert len(puts) == 1
    assert _put_payload(puts[0]) == {
        renamed: "Living Room Apple TV",
        kept: "Switch OLED",
    }
    assert f"settings delete secure {CUSTOM_LABELS_SETTING}" not in calls
    assert client.custom_labels[kept] == "Switch OLED"


def test_put_custom_labels_refuses_an_empty_map() -> None:
    client = _connected_client()
    calls: list[str] = []

    with patch.object(
        client, "shell", side_effect=lambda command: calls.append(command)
    ):
        assert client._put_custom_labels({}) is False  # noqa: SLF001

    assert calls == []


def test_delete_falls_back_to_null_when_firmware_refuses_delete() -> None:
    client = _connected_client()
    dropped = "com.tcl.tvinput/.TvPassThroughService/HW15"
    calls: list[str] = []

    def shell(command: str) -> str:
        calls.append(command)
        if command.startswith("settings get"):
            return format_custom_labels({dropped: "Apple TV"})
        if command.startswith("settings delete"):
            return "java.lang.SecurityException: delete not supported"
        return ""

    with (
        patch.object(client, "shell", side_effect=shell),
        patch.object(client, "ensure_connected", return_value=True),
    ):
        assert client.remove_hdmi_inputs({dropped}) is True

    assert f"settings delete secure {CUSTOM_LABELS_SETTING}" in calls
    assert f"settings put secure {CUSTOM_LABELS_SETTING} null" in calls
    assert client.custom_labels == {}
