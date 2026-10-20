"""Source handling shared by the media player and the source select."""

from __future__ import annotations

from typing import Any

from androidtvremote2 import AndroidTVRemote, ConnectionClosed

from homeassistant.exceptions import HomeAssistantError

from .adb import HDMI_NAME_RE, AdbClient, HdmiSource
from .const import CONF_APP_NAME, DOMAIN, GENERIC_HDMI_SOURCES
from .coordinator import AdbDataCoordinator


class SourceManager:
    """Single source of truth for the source list, current source and switching.

    HDMI inputs come from ADB; apps come from the configured app list and are
    launched over the Android TV Remote protocol.
    """

    def __init__(
        self,
        api: AndroidTVRemote,
        apps: dict[str, dict[str, Any]],
        adb: AdbClient | None = None,
        coordinator: AdbDataCoordinator | None = None,
    ) -> None:
        self.api = api
        self.apps = apps
        self.adb = adb
        self.coordinator = coordinator

    @property
    def adb_available(self) -> bool:
        if self.coordinator and self.coordinator.data:
            return self.coordinator.data.available
        return bool(self.adb and self.adb.available)

    def hdmi_sources(self) -> list[HdmiSource]:
        if self.coordinator and self.coordinator.data:
            return list(self.coordinator.data.hdmi_sources)
        if self.adb:
            return self.adb.hdmi_sources
        return []

    def app_name(self, package: str) -> str:
        """Friendly name for a package, or the package itself."""
        app = self.apps.get(package)
        if app and app.get(CONF_APP_NAME):
            return app[CONF_APP_NAME]
        return package

    def app_package(self, name: str) -> str:
        """Package for a friendly name, or the name itself (package / deep link)."""
        return next(
            (pid for pid, app in self.apps.items() if app.get(CONF_APP_NAME) == name),
            name,
        )

    def source_list(self) -> list[str]:
        """HDMI inputs first (when ADB is enabled), then configured apps."""
        sources: list[str] = []
        for hdmi in self.hdmi_sources():
            if hdmi.name not in sources:
                sources.append(hdmi.name)
        if not sources and self.adb_available:
            sources = list(GENERIC_HDMI_SOURCES)
        for package in self.apps:
            name = self.app_name(package)
            if name not in sources:
                sources.append(name)
        return sources

    def current_source(self) -> str | None:
        """Active HDMI input when on one, else the current app's friendly name."""
        if self.coordinator and self.coordinator.data:
            if name := self.coordinator.data.current_source_name:
                return name
        current = self.api.current_app
        if not current:
            return None
        if current in self.apps:
            return self.app_name(current)
        # Don't present system / launcher package names as a "source"
        if current.startswith("com.") and "hdmi" not in current.lower():
            return None
        return current

    def is_hdmi(self, name: str) -> bool:
        target = name.casefold().strip()
        if HDMI_NAME_RE.match(target):
            return True
        return any(
            h.name.casefold() == target
            or (h.cec_label and h.cec_label.casefold() == target)
            for h in self.hdmi_sources()
        )

    async def async_select(self, name: str) -> None:
        """Switch to an HDMI input (via ADB) or launch an app (remote protocol)."""
        if self.is_hdmi(name):
            if self.coordinator is None or self.adb is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="adb_disabled",
                    translation_placeholders={"source": name},
                )
            if not await self.coordinator.async_select_hdmi(name):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="hdmi_switch_failed",
                    translation_placeholders={
                        "source": name,
                        "error": self.adb.last_error or "unknown",
                    },
                )
            return
        self.launch_app(self.app_package(name))

    def launch_app(self, app_link: str) -> None:
        """Launch an app; must be called from the event loop."""
        try:
            self.api.send_launch_app_command(app_link)
        except ConnectionClosed as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="connection_closed"
            ) from exc
