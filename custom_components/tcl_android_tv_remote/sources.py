"""Source handling shared by the media player and the source select.

HDMI inputs are discovered over ADB (`dumpsys tv_input` plus the TV setting
`tv_input_custom_labels`). Until the user rebuilds, removes or refreshes,
that live list is what Home Assistant shows. Those actions save a catalog in
the config entry options:

* `hdmi_inputs` — the inputs on the source list, including any custom name
* `hdmi_removed` — input ids the user removed

The keep-alive poll merges inputs the TV still reports into that catalog and
does not delete saved inputs the poll missed, and it does not resurrect a
removed id. Refresh HDMI replaces the catalog with the TV's report, so a
removed input comes back when the TV still has it. Rebuild sources deletes
every saved input and every custom name on the TV, then discovers again.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from androidtvremote2 import AndroidTVRemote, ConnectionClosed

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .adb import HDMI_NAME_RE, AdbClient, HdmiSource
from .const import (
    CONF_APP_NAME,
    CONF_HDMI_INPUTS,
    CONF_HDMI_REMOVED,
    DOMAIN,
    GENERIC_HDMI_SOURCES,
)
from .coordinator import AdbDataCoordinator
from .helpers import TclAndroidTvRemoteConfigEntry

_LOGGER = logging.getLogger(__name__)

# Entity unique ids for an input start with "{entry unique id}_hdmi_".
# The media player and the Source select do not: they stay when an input goes.
_HDMI_ENTITY_PREFIX = "_hdmi_"
_AMBIGUOUS = object()


def format_input_label(source: HdmiSource) -> str:
    """Label for the options multi-select: name, port and hardware tail."""
    parts = [source.name]
    if source.port is not None and source.name.casefold() != f"hdmi {source.port}":
        parts.append(f"HDMI {source.port}")
    tail = source.input_id.rsplit("/", 1)[-1]
    if tail and tail.casefold() not in source.name.casefold():
        parts.append(tail)
    return " — ".join(parts)


def dump_hdmi_source(source: HdmiSource, labels: dict[str, str]) -> dict[str, Any]:
    """JSON-safe options value for one input. The dict key is the input id."""
    data: dict[str, Any] = {"name": source.name}
    if source.port is not None:
        data["port"] = source.port
    if source.cec_label:
        data["cec_label"] = source.cec_label
    custom = labels.get(source.input_id)
    if isinstance(custom, str) and custom:
        data["custom_name"] = custom
    return data


def load_hdmi_source(input_id: str, raw: Any) -> HdmiSource | None:
    """Restore one saved input. None when the stored value is unusable."""
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        return None
    port = raw.get("port")
    if isinstance(port, bool) or not isinstance(port, int):
        port = None
    cec = raw.get("cec_label")
    custom = raw.get("custom_name")
    label = cec if isinstance(cec, str) and cec else None
    if label is None and isinstance(custom, str) and custom:
        label = custom
    return HdmiSource(name=name, input_id=input_id, port=port, cec_label=label)


def hdmi_entity_unique_id(entry_unique_id: str, input_id: str) -> str:
    """Unique id for an entity that belongs to one HDMI input."""
    safe = re.sub(r"[^A-Za-z0-9]+", "_", input_id).strip("_")
    return f"{entry_unique_id}{_HDMI_ENTITY_PREFIX}{safe}"


def match_hdmi_tokens(
    sources: list[HdmiSource], tokens: list[str]
) -> tuple[list[HdmiSource], list[str], list[str]]:
    """Resolve ids and names to inputs.

    Returns (matched, unknown tokens, ambiguous tokens). Matching is exact
    on the input id, its hardware tail, the display name, the CEC / custom
    label and "HDMI N", then a partial name when that hits one input.
    """
    matched: dict[str, HdmiSource] = {}
    unknown: list[str] = []
    ambiguous: list[str] = []
    for token in tokens:
        found = _match_one(sources, token)
        if found is _AMBIGUOUS:
            ambiguous.append(token)
        elif found is None:
            unknown.append(token)
        elif isinstance(found, HdmiSource):
            matched[found.input_id] = found
    return list(matched.values()), unknown, ambiguous


def _match_one(sources: list[HdmiSource], token: str) -> HdmiSource | object | None:
    target = token.strip()
    folded = target.casefold()
    if not folded:
        return None

    def _one(hits: list[HdmiSource]) -> HdmiSource | object | None:
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return _AMBIGUOUS
        return None

    exact_id = _one(
        [
            src
            for src in sources
            if src.input_id == target or src.input_id.casefold() == folded
        ]
    )
    if exact_id is not None:
        return exact_id

    tail = _one(
        [src for src in sources if src.input_id.rsplit("/", 1)[-1].casefold() == folded]
    )
    if tail is not None:
        return tail

    named = _one([src for src in sources if src.name.casefold() == folded])
    if named is not None:
        return named

    labeled = _one(
        [src for src in sources if src.cec_label and src.cec_label.casefold() == folded]
    )
    if labeled is not None:
        return labeled

    port = _one(
        [
            src
            for src in sources
            if src.port is not None
            and folded in {f"hdmi {src.port}", f"hdmi{src.port}"}
        ]
    )
    if port is not None:
        return port

    partial = [
        src
        for src in sources
        if folded in src.name.casefold()
        or (src.cec_label and folded in src.cec_label.casefold())
    ]
    return _one(partial)


class HdmiCatalog:
    """Saved HDMI inputs and the ids the user has removed, in entry options."""

    def __init__(
        self, hass: HomeAssistant, entry: TclAndroidTvRemoteConfigEntry
    ) -> None:
        self.hass = hass
        self.entry = entry

    def explicit(self) -> bool:
        """True once a rebuild, remove or refresh has saved a catalog."""
        options = self.entry.options
        return CONF_HDMI_INPUTS in options or CONF_HDMI_REMOVED in options

    def inputs(self) -> dict[str, Any]:
        raw = self.entry.options.get(CONF_HDMI_INPUTS, {})
        return dict(raw) if isinstance(raw, dict) else {}

    def removed_ids(self) -> set[str]:
        raw = self.entry.options.get(CONF_HDMI_REMOVED, [])
        if not isinstance(raw, list):
            return set()
        return {item for item in raw if isinstance(item, str)}

    def visible_sources(self) -> list[HdmiSource]:
        removed = self.removed_ids()
        sources: list[HdmiSource] = []
        for input_id, raw in self.inputs().items():
            if input_id in removed:
                continue
            source = load_hdmi_source(input_id, raw)
            if source is not None:
                sources.append(source)
        return sources

    def replace(
        self,
        sources: list[HdmiSource],
        labels: dict[str, str],
        removed: set[str],
        *,
        preserve_custom: bool,
    ) -> None:
        """Store this list. `preserve_custom` keeps a mapping the TV read missed."""
        previous = self.inputs()
        stored: dict[str, Any] = {}
        for source in sources:
            if source.input_id in removed:
                continue
            dumped = dump_hdmi_source(source, labels)
            prev = previous.get(source.input_id)
            if (
                preserve_custom
                and isinstance(prev, dict)
                and isinstance(prev.get("custom_name"), str)
                and "custom_name" not in dumped
            ):
                dumped["custom_name"] = prev["custom_name"]
            stored[source.input_id] = dumped
        self._write(stored, removed)

    def merge(self, sources: list[HdmiSource], labels: dict[str, str]) -> None:
        """Add or update inputs the TV reports, skipping removed ids.

        Inputs already saved but missing from this report stay. A keep-alive
        that fails halfway must not drop a port that is still plugged in.
        """
        if not self.explicit():
            return
        removed = self.removed_ids()
        current = self.inputs()
        changed = False
        for source in sources:
            if source.input_id in removed:
                continue
            dumped = dump_hdmi_source(source, labels)
            prev = current.get(source.input_id)
            if isinstance(prev, dict) and isinstance(prev.get("custom_name"), str):
                if "custom_name" not in dumped:
                    dumped["custom_name"] = prev["custom_name"]
            if prev != dumped:
                current[source.input_id] = dumped
                changed = True
        if changed:
            self._write(current, removed)

    def _write(self, inputs: dict[str, Any], removed: set[str]) -> None:
        removed_list = sorted(removed)
        options = self.entry.options
        if (
            options.get(CONF_HDMI_INPUTS) == inputs
            and options.get(CONF_HDMI_REMOVED) == removed_list
        ):
            return
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={
                **options,
                CONF_HDMI_INPUTS: inputs,
                CONF_HDMI_REMOVED: removed_list,
            },
        )


def async_purge_orphaned_hdmi_entities(
    hass: HomeAssistant,
    entry: TclAndroidTvRemoteConfigEntry,
    current_input_ids: set[str],
) -> None:
    """Drop entity-registry entries that belonged to an input which is gone.

    The source list itself is the media player plus one Source select, and
    those stay. Anything created for a single input uses a unique id with
    the `_hdmi_` prefix; once that input is no longer saved, the entity is
    removed so it does not linger as unavailable.
    """
    unique = entry.unique_id
    if not unique:
        return
    prefix = f"{unique}{_HDMI_ENTITY_PREFIX}"
    keep = {hdmi_entity_unique_id(unique, input_id) for input_id in current_input_ids}
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        entity_unique = entity.unique_id or ""
        if entity_unique.startswith(prefix) and entity_unique not in keep:
            registry.async_remove(entity.entity_id)


class SourceManager:
    """Single source of truth for the source list, current source and switching.

    HDMI inputs come from ADB; apps come from the configured app list and are
    launched over the Android TV Remote protocol.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: TclAndroidTvRemoteConfigEntry,
        api: AndroidTVRemote,
        apps: dict[str, dict[str, Any]],
        adb: AdbClient | None = None,
        coordinator: AdbDataCoordinator | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.api = api
        self.apps = apps
        self.adb = adb
        self.coordinator = coordinator
        self._catalog = HdmiCatalog(hass, entry)
        if coordinator is not None:
            coordinator.set_source_hooks(
                self.sync_saved_from_discovery, self.accept_tv_report
            )

    @property
    def adb_available(self) -> bool:
        if self.coordinator and self.coordinator.data:
            return self.coordinator.data.available
        return bool(self.adb and self.adb.available)

    def catalog_explicit(self) -> bool:
        return self._catalog.explicit()

    def removed_input_ids(self) -> list[str]:
        return sorted(self._catalog.removed_ids())

    def hdmi_sources(self) -> list[HdmiSource]:
        if self._catalog.explicit():
            return self._catalog.visible_sources()
        if self.coordinator and self.coordinator.data:
            return list(self.coordinator.data.hdmi_sources)
        if self.adb:
            return self._adb_sources()
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
        # Generic HDMI 1–4 is only a stand-in before the first real discovery.
        # An explicit catalog, even an empty one, means the user chose the list.
        if not sources and self.adb_available and not self._catalog.explicit():
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

    def sync_saved_from_discovery(self) -> None:
        """Keep-alive: fold the latest TV report into the saved catalog."""
        if self.adb is None or not self._catalog.explicit():
            return
        self._catalog.merge(self._adb_sources(), self._labels())

    def accept_tv_report(self) -> None:
        """Refresh HDMI: the saved list becomes exactly what the TV reports."""
        if self.adb is None or not self._catalog.explicit():
            return
        self._catalog.replace(
            self._adb_sources(),
            self._labels(),
            set(),
            preserve_custom=False,
        )
        # The coordinator notifies listeners when this update finishes.
        self._purge()

    async def async_rebuild(self) -> None:
        """Forget every saved input and custom name, then discover again."""
        self._require_adb()
        assert self.adb is not None
        cleared = await self.hass.async_add_executor_job(self.adb.rebuild_hdmi_sources)
        sources = self._adb_sources()
        self._catalog.replace(sources, self._labels(), set(), preserve_custom=False)
        self._publish()
        self._purge()
        _LOGGER.info(
            "Rebuilt HDMI sources for %s (%d input(s), custom names %s)",
            self.entry.title,
            len(sources),
            "cleared" if cleared else "unchanged",
        )
        if not cleared:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="hdmi_labels_failed",
                translation_placeholders={
                    "name": self.entry.title,
                    "error": self.adb.last_error or "unknown",
                },
            )

    async def async_remove(self, tokens: list[str]) -> None:
        """Remove inputs by id or name, and delete their custom names on the TV.

        The next keep-alive leaves them out. Refresh HDMI adds back any input
        the TV still reports.
        """
        self._require_adb()
        assert self.adb is not None
        cleaned = [token.strip() for token in tokens if token and token.strip()]
        if not cleaned:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="hdmi_inputs_required",
            )
        matched, unknown, ambiguous = match_hdmi_tokens(self.hdmi_sources(), cleaned)
        if ambiguous:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="ambiguous_hdmi_inputs",
                translation_placeholders={"inputs": ", ".join(ambiguous)},
            )
        if unknown:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_hdmi_inputs",
                translation_placeholders={"inputs": ", ".join(unknown)},
            )
        remove_ids = {source.input_id for source in matched}
        if not self._catalog.explicit():
            # Snapshot the live list so this removal survives the next poll.
            self._catalog.replace(
                self.hdmi_sources(),
                self._labels(),
                set(),
                preserve_custom=True,
            )
        labels_ok = await self.hass.async_add_executor_job(
            self.adb.remove_hdmi_inputs, remove_ids
        )
        remaining = [
            source
            for source in self.hdmi_sources()
            if source.input_id not in remove_ids
        ]
        self._catalog.replace(
            remaining,
            self._labels(),
            self._catalog.removed_ids() | remove_ids,
            preserve_custom=True,
        )
        self._publish()
        self._purge()
        _LOGGER.info(
            "Removed HDMI inputs from %s: %s",
            self.entry.title,
            ", ".join(sorted(remove_ids)),
        )
        if not labels_ok:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="hdmi_labels_failed",
                translation_placeholders={
                    "name": self.entry.title,
                    "error": self.adb.last_error or "unknown",
                },
            )

    def _require_adb(self) -> None:
        if self.adb is None or self.coordinator is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="adb_not_enabled",
                translation_placeholders={"name": self.entry.title},
            )

    def _adb_sources(self) -> list[HdmiSource]:
        if self.adb is None:
            return []
        sources = self.adb.hdmi_sources
        if isinstance(sources, list):
            return list(sources)
        return []

    def _labels(self) -> dict[str, str]:
        if self.adb is None:
            return {}
        labels = self.adb.custom_labels
        if isinstance(labels, dict):
            return labels
        return {}

    def _publish(self) -> None:
        """Ask the media player and Source select to reload their lists."""
        coordinator = self.coordinator
        if coordinator is None:
            return
        if coordinator.data is not None:
            coordinator.async_set_updated_data(coordinator.data)
            return
        coordinator.async_update_listeners()

    def _purge(self) -> None:
        async_purge_orphaned_hdmi_entities(
            self.hass,
            self.entry,
            {source.input_id for source in self.hdmi_sources()},
        )
