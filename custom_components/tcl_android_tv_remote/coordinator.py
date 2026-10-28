"""ADB data coordinator: keep-alive, TLS port tracking, HDMI / media refresh."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .adb import AdbClient, HdmiSource, MediaMetadata
from .const import DOMAIN, KEEPALIVE_INTERVAL_MIN
from .helpers import discover_connect_port

_LOGGER = logging.getLogger(__name__)


@dataclass
class AdbCoordinatorData:
    """Snapshot of ADB state."""

    available: bool = False
    status: str = "disconnected"  # connected | unauthorized | offline | timeout | error
    hdmi_sources: list[HdmiSource] = field(default_factory=list)
    active_input: str | None = None
    current_source_name: str | None = None
    media: MediaMetadata | None = None
    last_error: str | None = None
    last_success: datetime | None = None
    host: str | None = None
    port: int | None = None


def adb_issue_id(entry_id: str) -> str:
    """Repair issue id for an entry's ADB offline issue."""
    return f"adb_offline_{entry_id}"


class AdbDataCoordinator(DataUpdateCoordinator[AdbCoordinatorData]):
    """Periodically keep ADB alive and refresh HDMI / media state."""

    def __init__(
        self,
        hass: HomeAssistant,
        adb: AdbClient,
        update_interval: int,
        *,
        entry_id: str,
        device_name: str,
        on_port_changed: Callable[[int], None] | None = None,
    ) -> None:
        self.adb = adb
        self.entry_id = entry_id
        self.device_name = device_name
        self._on_port_changed = on_port_changed
        self._was_available: bool | None = None
        self._last_success: datetime | None = None
        # Keep-alive merges the TV report into the saved catalog. An explicit
        # refresh replaces that catalog so removed inputs can come back.
        self._sync_sources: Callable[[], None] | None = None
        self._accept_tv_sources: Callable[[], None] | None = None
        self._accept_reported_sources = False
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_adb_{entry_id}",
            update_interval=timedelta(
                seconds=max(KEEPALIVE_INTERVAL_MIN, update_interval)
            ),
        )

    async def _async_rediscover_tls_port(self) -> bool:
        """Look up the current TLS connect port; return True if it changed."""
        port = await discover_connect_port(self.hass, self.adb.host)
        if not port or port == self.adb.port:
            return False
        _LOGGER.info(
            "%s: Wireless debugging port changed %s → %s",
            self.device_name,
            self.adb.port,
            port,
        )
        self.adb.port = port
        if self._on_port_changed:
            self._on_port_changed(port)
        return True

    async def _async_update_data(self) -> AdbCoordinatorData:
        ok = await self.hass.async_add_executor_job(self.adb.keep_alive_tick)
        if not ok and self.adb.use_tls and await self._async_rediscover_tls_port():
            ok = await self.hass.async_add_executor_job(self.adb.keep_alive_tick)

        available = bool(ok and self.adb.available)
        if available:
            self._last_success = dt_util.now()

        data = AdbCoordinatorData(
            available=available,
            status="connected" if available else (self.adb.status or "offline"),
            hdmi_sources=self.adb.hdmi_sources,
            active_input=self.adb.active_input,
            current_source_name=self.adb.current_source_name(),
            media=self.adb.media,
            last_error=None if available else self._error_text(),
            last_success=self._last_success,
            host=self.adb.host,
            port=self.adb.port,
        )
        self._handle_availability(data)
        if self._accept_reported_sources and self._accept_tv_sources is not None:
            self._accept_tv_sources()
        elif self._sync_sources is not None:
            self._sync_sources()
        return data

    def _error_text(self) -> str:
        if self.adb.last_error:
            return self.adb.last_error
        if self.adb.use_tls:
            return "ADB not available (Wireless debugging off or not paired)"
        return "ADB not available (Network debugging off or unauthorized)"

    def _handle_availability(self, data: AdbCoordinatorData) -> None:
        """Raise / clear the repair issue when ADB drops or recovers."""
        if data.available == self._was_available:
            return
        self._was_available = data.available
        issue_id = adb_issue_id(self.entry_id)
        if data.available:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            _LOGGER.info("%s: ADB online", self.device_name)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=(
                "adb_offline_tls" if self.adb.use_tls else "adb_offline_classic"
            ),
            translation_placeholders={
                "name": self.device_name,
                "port": str(self.adb.port),
                "error": data.last_error or "unknown",
            },
        )

    def set_source_hooks(
        self,
        sync_sources: Callable[[], None],
        accept_tv_sources: Callable[[], None],
    ) -> None:
        """Register catalog updates run at the end of a successful refresh.

        `sync_sources` merges inputs the TV reports and leaves saved inputs
        the TV did not mention alone (a short ADB failure must not wipe the
        list). `accept_tv_sources` replaces the saved list with the report.
        """
        self._sync_sources = sync_sources
        self._accept_tv_sources = accept_tv_sources

    async def async_refresh_hdmi(self) -> AdbCoordinatorData:
        """Reconnect if needed, rediscover HDMI inputs and push new state.

        Unlike the keep-alive poll, this replaces the saved input list with
        what the TV reports, which brings back an input the user removed.
        """
        self._accept_reported_sources = True
        try:
            await self.async_refresh()
        finally:
            self._accept_reported_sources = False
        return self.data

    async def async_adb_command(self, command: str) -> str | None:
        """Run a shell command, reconnecting first if needed."""
        if not await self.hass.async_add_executor_job(self.adb.ensure_connected):
            if not (
                self.adb.use_tls
                and await self._async_rediscover_tls_port()
                and await self.hass.async_add_executor_job(self.adb.ensure_connected)
            ):
                return None
        return await self.hass.async_add_executor_job(self.adb.shell, command)

    async def async_select_hdmi(self, name: str) -> bool:
        """Switch to an HDMI input by name, retrying once after a refresh."""
        ok = await self.hass.async_add_executor_job(self.adb.select_hdmi_by_name, name)
        if not ok:
            await self.hass.async_add_executor_job(self.adb.refresh_hdmi)
            ok = await self.hass.async_add_executor_job(
                self.adb.select_hdmi_by_name, name
            )
        await self.async_request_refresh()
        return ok
