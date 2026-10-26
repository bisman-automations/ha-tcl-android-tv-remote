"""Services for TCL Android TV Remote."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.service import async_register_admin_service

try:  # Home Assistant 2025.9+; the old location was removed in 2026.10
    from homeassistant.helpers.target import (
        TargetSelection,
        async_extract_referenced_entity_ids as _extract_referenced,
    )

    def _referenced_entities(hass: HomeAssistant, call: ServiceCall):
        return _extract_referenced(hass, TargetSelection(call.data))

except ImportError:  # pragma: no cover - older Home Assistant
    from homeassistant.helpers.service import (
        async_extract_referenced_entity_ids as _extract_referenced_legacy,
    )

    def _referenced_entities(hass: HomeAssistant, call: ServiceCall):
        return _extract_referenced_legacy(hass, call)


from .const import (
    ADB_MODE_TLS,
    ADB_PORT_DISCOVER,
    ATTR_COMMAND,
    ATTR_PAIRING_CODE,
    ATTR_PAIRING_PORT,
    CONF_ADB_MODE,
    CONF_ADB_PORT,
    CONF_ENABLE_ADB,
    DOMAIN,
    SERVICE_ADB_COMMAND,
    SERVICE_ADB_PAIR,
    SERVICE_REFRESH_HDMI,
)
from .helpers import TclAndroidTvRemoteConfigEntry, create_adb, discover_connect_port

_LOGGER = logging.getLogger(__name__)

_TARGET = cv.make_entity_service_schema({})

REFRESH_HDMI_SCHEMA = _TARGET
ADB_COMMAND_SCHEMA = cv.make_entity_service_schema(
    {vol.Required(ATTR_COMMAND): cv.string}
)
ADB_PAIR_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_PAIRING_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1024, max=65535)
        ),
        vol.Required(ATTR_PAIRING_CODE): cv.string,
    }
)


def _target_entries(
    hass: HomeAssistant, call: ServiceCall
) -> list[TclAndroidTvRemoteConfigEntry]:
    """Resolve the call's target (entities, devices, areas) to loaded entries.

    Never falls back to "every TV": a call with no matching target is an error.
    """
    selected = _referenced_entities(hass, call)
    entity_reg = er.async_get(hass)
    entries: dict[str, TclAndroidTvRemoteConfigEntry] = {}
    for entity_id in selected.referenced | selected.indirectly_referenced:
        ent = entity_reg.async_get(entity_id)
        if not ent or not ent.config_entry_id:
            continue
        entry = hass.config_entries.async_get_entry(ent.config_entry_id)
        if entry and entry.domain == DOMAIN and entry.state is ConfigEntryState.LOADED:
            entries[entry.entry_id] = entry
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_target"
        )
    return list(entries.values())


def _require_coordinator(entry: TclAndroidTvRemoteConfigEntry):
    coordinator = entry.runtime_data.coordinator
    if coordinator is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="adb_not_enabled",
            translation_placeholders={"name": entry.title},
        )
    return coordinator


def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration services."""

    async def handle_refresh_hdmi(call: ServiceCall) -> None:
        for entry in _target_entries(hass, call):
            await _require_coordinator(entry).async_refresh_hdmi()

    async def handle_adb_command(call: ServiceCall) -> ServiceResponse:
        command: str = call.data[ATTR_COMMAND]
        results: dict[str, str | None] = {}
        for entry in _target_entries(hass, call):
            coordinator = _require_coordinator(entry)
            output = await coordinator.async_adb_command(command)
            if output is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="adb_command_failed",
                    translation_placeholders={
                        "name": entry.title,
                        "error": coordinator.adb.last_error or "unknown",
                    },
                )
            results[entry.title] = output
        return {"results": results}

    async def handle_adb_pair(call: ServiceCall) -> None:
        """Pair using Android 11+ wireless debugging, then switch to TLS."""
        port: int = call.data[ATTR_PAIRING_PORT]
        code: str = call.data[ATTR_PAIRING_CODE]
        for entry in _target_entries(hass, call):
            host = entry.data[CONF_HOST]
            adb = create_adb(hass, host, ADB_PORT_DISCOVER, use_tls=True)
            if not await hass.async_add_executor_job(adb.pair_wireless, port, code):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="adb_pair_failed",
                    translation_placeholders={
                        "name": entry.title,
                        "error": adb.last_error or "unknown",
                    },
                )
            connect_port = await discover_connect_port(hass, host)
            hass.config_entries.async_update_entry(
                entry,
                options={
                    **entry.options,
                    CONF_ENABLE_ADB: True,
                    CONF_ADB_MODE: ADB_MODE_TLS,
                    CONF_ADB_PORT: connect_port or ADB_PORT_DISCOVER,
                },
            )
            _LOGGER.info(
                "Wireless ADB paired for %s (connect port %s)",
                entry.title,
                connect_port or "to be discovered",
            )
            hass.config_entries.async_schedule_reload(entry.entry_id)

    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH_HDMI, handle_refresh_hdmi, schema=REFRESH_HDMI_SCHEMA
    )
    # Arbitrary shell access and pairing are admin-only
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_ADB_COMMAND,
        handle_adb_command,
        schema=ADB_COMMAND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    async_register_admin_service(
        hass, DOMAIN, SERVICE_ADB_PAIR, handle_adb_pair, schema=ADB_PAIR_SCHEMA
    )
