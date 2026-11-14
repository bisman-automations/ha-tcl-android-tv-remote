"""Wireless debugging pairing needs adb-shell-wifi's optional "wifi" extra."""

from __future__ import annotations

import json
from pathlib import Path

MANIFEST = (
    Path(__file__).parent.parent
    / "custom_components"
    / "tcl_android_tv_remote"
    / "manifest.json"
)


def test_manifest_installs_the_wifi_extra() -> None:
    """Home Assistant installs spake2 and pyOpenSSL for pairing (issue #5)."""
    requirements = json.loads(MANIFEST.read_text())["requirements"]
    wifi = [r for r in requirements if r.startswith("adb-shell-wifi")]
    assert wifi == ["adb-shell-wifi[wifi]==0.5.0"]


def test_pairing_handshake_can_start() -> None:
    """The pairing code's SPAKE2 message is built without a missing module."""
    from adb_shell_wifi.pairing.auth import ROLE_CLIENT, PairingAuthCtx  # noqa: PLC0415
    from OpenSSL import SSL  # noqa: PLC0415, F401

    ctx = PairingAuthCtx(ROLE_CLIENT, b"123456")
    assert ctx.our_msg
