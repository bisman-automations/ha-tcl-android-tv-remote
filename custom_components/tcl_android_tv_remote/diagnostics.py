"""Diagnostics support for TCL Android TV Remote."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.core import HomeAssistant

from .const import CONF_APPS
from .helpers import TclAndroidTvRemoteConfigEntry, get_adb_mode

TO_REDACT = {CONF_HOST, CONF_MAC, "host"}
REDACTED = "**REDACTED**"


def _scrub(value: Any, pattern: re.Pattern[str] | None) -> Any:
    """Replace the TV's address inside free text (errors quote host:port)."""
    if pattern is None:
        return value
    if isinstance(value, str):
        return pattern.sub(REDACTED, value)
    if isinstance(value, dict):
        return {key: _scrub(item, pattern) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(item, pattern) for item in value]
    return value


def _address_pattern(entry: TclAndroidTvRemoteConfigEntry) -> re.Pattern[str] | None:
    values = [
        str(entry.data[key])
        for key in (CONF_HOST, CONF_MAC)
        if isinstance(entry.data.get(key), str) and entry.data[key]
    ]
    if not values:
        return None
    return re.compile(
        "|".join(re.escape(value) for value in sorted(values, key=len, reverse=True)),
        re.IGNORECASE,
    )


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TclAndroidTvRemoteConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    api = runtime.api
    coordinator = runtime.coordinator
    data = coordinator.data if coordinator else None

    adb: dict[str, Any] = {"enabled": coordinator is not None}
    if coordinator is not None:
        adb |= {
            "mode": get_adb_mode(entry),
            "port": coordinator.adb.port,
            "update_interval": coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None,
        }
    if data is not None:
        adb |= {
            "available": data.available,
            "status": data.status,
            "last_error": data.last_error,
            "last_success": data.last_success.isoformat()
            if data.last_success
            else None,
            "active_input": data.active_input,
            "current_source": data.current_source_name,
            "hdmi_sources": [
                {
                    "name": s.name,
                    "input_id": s.input_id,
                    "port": s.port,
                    "cec_label": s.cec_label,
                }
                for s in data.hdmi_sources
            ],
            "media": vars(data.media) if data.media else None,
        }

    return _scrub(
        async_redact_data(
            {
                "api_device_info": api.device_info,
                "api_is_on": api.is_on,
                "api_current_app": api.current_app,
                "config_entry_data": entry.data,
                "config_entry_options": {
                    k: v for k, v in entry.options.items() if k != CONF_APPS
                },
                "apps_count": len(entry.options.get(CONF_APPS, {})),
                "source_list": runtime.sources.source_list(),
                "removed_hdmi_inputs": runtime.sources.removed_input_ids(),
                "adb": adb,
            },
            TO_REDACT,
        ),
        _address_pattern(entry),
    )
