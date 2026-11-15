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


def test_manifest_lists_the_extra_itself() -> None:
    """The extra's packages are listed by name too (issue #5, after 1.1.6).

    Home Assistant decides whether a requirement is installed from its name
    and version only, ignoring extras. On an install that already had
    adb-shell-wifi 0.5.0, "adb-shell-wifi[wifi]==0.5.0" counted as installed
    and spake2 never came. Every package of the extra that Home Assistant
    doesn't ship itself must be in the manifest by its own name.
    """
    from importlib.metadata import requires  # noqa: PLC0415

    from packaging.requirements import Requirement  # noqa: PLC0415

    listed = {
        Requirement(r).name.lower()
        for r in json.loads(MANIFEST.read_text())["requirements"]
    }
    extra = {
        Requirement(r).name.lower()
        for r in requires("adb-shell-wifi") or []
        if 'extra == "wifi"' in r
    }
    assert extra - {"zeroconf"} <= listed


def test_pairing_handshake_can_start() -> None:
    """The pairing code's SPAKE2 message is built without a missing module."""
    from adb_shell_wifi.pairing.auth import ROLE_CLIENT, PairingAuthCtx  # noqa: PLC0415
    from OpenSSL import SSL  # noqa: PLC0415, F401

    ctx = PairingAuthCtx(ROLE_CLIENT, b"123456")
    assert ctx.our_msg
