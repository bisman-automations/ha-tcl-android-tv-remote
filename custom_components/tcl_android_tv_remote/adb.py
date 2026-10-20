"""ADB helpers: HDMI (CEC labels), media metadata, locked shell access."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import re
import threading
from typing import Any
from urllib.parse import unquote

_LOGGER = logging.getLogger(__name__)

HDMI_NAME_RE = re.compile(r"(?i)^hdmi\s*(\d+)$")
ACTIVE_INPUT_RE = re.compile(r"inputId:\s+([^\s]+)")
# Also catch TCL-style "state: 1" lines that include the full input id
INPUT_STATE_RE = re.compile(
    r"(?P<input_id>[\w.]+/[\w.$]+(?:/[\w.$]+)*(?:/HW\d+|/HDMI\d+)?)"
    r".*?state:\s*(?P<state>\d+)",
    re.I,
)
INPUT_ID_RE = re.compile(
    r"(?P<input_id>[\w.]+/[\w.$]+(?:/[\w.$]+)*(?:/HW\d+|/HDMI\d+)?)"
)
HDMI_PORT_INFO_RE = re.compile(r"hdmi_port=(?P<port>\d+)", re.I)
HARDWARE_INFO_RE = re.compile(
    r"TvInputHardwareInfo\s+\{id=(?P<id>\d+),\s*type=(?P<type>\d+).*?\}",
    re.I,
)
HARDWARE_INPUT_MAP_RE = re.compile(
    r"(?P<hardware_id>\d+):\s+(?P<input_id>[\w.]+/[\w.$]+(?:/[\w.$]+)*)"
)
HDMI_CEC_DEVICE_RE = re.compile(
    r"CEC:.*?display_name:\s*(?P<label>.*?)\s+power_status:.*?port_id:\s*(?P<port>\d+)",
    re.I,
)
# Fallback when custom labels / dumpsys are incomplete (TCL common mapping)
TCL_HW_FALLBACK_NAMES = {
    15: "HDMI 1",
    16: "HDMI 2",
    17: "HDMI 3",
    18: "HDMI 4",
    2: "Antenna TV",
}
METADATA_FIELD_PATTERNS = {
    "title": (
        re.compile(
            r"(?:android\.media\.metadata\.TITLE|title)\s*[=:]\s*(?P<value>[^,\n\}]+)",
            re.I,
        ),
        re.compile(r'description="(?P<value>[^"]+)"', re.I),
    ),
    "artist": (
        re.compile(
            r"(?:android\.media\.metadata\.ARTIST|artist)\s*[=:]\s*(?P<value>[^,\n\}]+)",
            re.I,
        ),
    ),
    "album": (
        re.compile(
            r"(?:android\.media\.metadata\.ALBUM|album)\s*[=:]\s*(?P<value>[^,\n\}]+)",
            re.I,
        ),
    ),
    "image_url": (
        re.compile(
            r"(?:android\.media\.metadata\.ART_URI|artUri|iconUri|mediaUri)\s*[=:]\s*(?P<value>[^,\s\}\"]+)",
            re.I,
        ),
    ),
    "playback_state": (
        re.compile(r"state=PlaybackState\s*\{(?P<value>[^,\}]+)", re.I),
    ),
}
PLAYBACK_STATE_NAMES = {
    "0": "idle",
    "1": "stopped",
    "2": "paused",
    "3": "playing",
    "4": "fast_forwarding",
    "5": "rewinding",
    "6": "buffering",
    "7": "error",
}


@dataclass
class HdmiSource:
    """Physical TV input discovered via ADB."""

    name: str
    input_id: str
    port: int | None = None
    cec_label: str | None = None

    @property
    def passthrough_uri(self) -> str:
        """Standard Android TV passthrough URI (path segments URL-encoded)."""
        encoded = self.input_id.replace("/", "%2F")
        return f"content://android.media.tv/passthrough/{encoded}"

    @property
    def passthrough_uri_raw(self) -> str:
        """Passthrough URI without encoding (some TCL builds prefer this)."""
        return f"content://android.media.tv/passthrough/{self.input_id}"


@dataclass
class MediaMetadata:
    """Now-playing style metadata from media_session dumpsys."""

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    image_url: str | None = None
    playback_state: str | None = None


def extract_active_tv_input(dumpsys: str) -> str | None:
    matches = ACTIVE_INPUT_RE.findall(dumpsys)
    return matches[-1] if matches else None


def _clean_label(label: str) -> str | None:
    cleaned = label.strip().strip("'\"")
    cleaned = re.split(
        r"\s+(?:hdmi[_ ]?port|port|input|state|type|hardware)[=:]",
        cleaned,
        maxsplit=1,
        flags=re.I,
    )[0].strip()
    if not cleaned or cleaned.lower() in {"null", "none"}:
        return None
    return cleaned


def _looks_like_physical_input(input_id: str) -> bool:
    """True for passthrough inputs ending in HW<n> / HDMI<n>, or any id naming HDMI."""
    tail = input_id.rsplit("/", 1)[-1]
    return bool(
        re.fullmatch(r"(?i)hw\d+|hdmi\d{1,2}", tail) or "hdmi" in input_id.lower()
    )


def parse_custom_labels(raw: str | None) -> dict[str, str]:
    """Parse `settings get secure tv_input_custom_labels` output.

    Format: inputId,Label:inputId,Label:... where both parts are URL-encoded,
    so ":" and "," inside a label arrive as %3A / %2C and survive the split.
    """
    if not raw or raw.strip() in {"null", "None"}:
        return {}
    result: dict[str, str] = {}
    for part in raw.strip().split(":"):
        if "," not in part:
            continue
        input_id, label = part.split(",", 1)
        input_id = unquote(input_id).strip()
        label = unquote(label).strip()
        if input_id and label:
            result[input_id] = label
    return result


def extract_hdmi_sources(
    dumpsys: str,
    custom_labels: dict[str, str] | None = None,
) -> list[HdmiSource]:
    """Parse physical HDMI / tuner inputs with custom + CEC labels.

    Tuned for TCL firmwares that expose:
      com.tcl.tvinput/.TvPassThroughService/HW15  (hdmi_port=1)
      com.tcl.tvinput/.TvPassThroughService/HW16  (hdmi_port=2)
      ...
    and store friendly names in tv_input_custom_labels.
    """
    custom_labels = custom_labels or {}

    hardware: dict[str, dict[str, int | None]] = {}
    for match in HARDWARE_INFO_RE.finditer(dumpsys):
        raw = match.group(0)
        port_match = HDMI_PORT_INFO_RE.search(raw)
        hardware[match.group("id")] = {
            "type": int(match.group("type")),
            "port": int(port_match.group("port")) if port_match else None,
        }

    cec_labels: dict[int, str] = {}
    for match in HDMI_CEC_DEVICE_RE.finditer(dumpsys):
        label = _clean_label(match.group("label"))
        if label:
            cec_labels[int(match.group("port"))] = label

    input_ids: dict[str, None] = {}
    for line in dumpsys.splitlines():
        match = INPUT_ID_RE.search(line)
        if match and _looks_like_physical_input(match.group("input_id")):
            input_ids[match.group("input_id")] = None
        map_match = HARDWARE_INPUT_MAP_RE.search(line)
        if map_match and _looks_like_physical_input(map_match.group("input_id")):
            input_ids[map_match.group("input_id")] = None

    # Also pull every key from custom labels that looks physical
    for input_id in custom_labels:
        if _looks_like_physical_input(input_id):
            input_ids[input_id] = None

    found: dict[str, HdmiSource] = {}
    for input_id in input_ids:
        port: int | None = None
        hw_id: int | None = None
        hw_match = re.search(r"(?:HW|HDMI)(?P<hid>\d+)$", input_id, re.I)
        input_type: int | None = None
        if hw_match:
            hw_id = int(hw_match.group("hid"))
            # Ignore absurd hardware ids (e.g. HDMI30004 noise from dumpsys)
            if hw_id > 64:
                continue
            if str(hw_id) in hardware:
                info = hardware[str(hw_id)]
                port = info.get("port")  # type: ignore[assignment]
                input_type = info.get("type")  # type: ignore[assignment]

        # Prefer TV Settings custom label → CEC name → generic HDMI N
        custom = custom_labels.get(input_id)
        cec = cec_labels.get(port) if port is not None else None
        fallback = TCL_HW_FALLBACK_NAMES.get(hw_id) if hw_id is not None else None

        if custom:
            name = custom
        elif cec and port is not None:
            name = f"HDMI {port} - {cec}"
        elif port is not None:
            name = f"HDMI {port}"
        elif fallback:
            name = fallback
        elif input_type == 2:
            name = "Tuner"
        else:
            tail = input_id.rsplit("/", 1)[-1]
            # Skip raw HW## / HDMI#### tails — not user-friendly
            if re.fullmatch(r"(?i)(hw|hdmi)\d+", tail):
                if hw_id is not None and hw_id in TCL_HW_FALLBACK_NAMES:
                    name = TCL_HW_FALLBACK_NAMES[hw_id]
                else:
                    continue
            else:
                name = tail

        # Drop garbage display names (HDMI30004, HW17, etc.)
        if re.fullmatch(r"(?i)hdmi\d{3,}", name.replace(" ", "")):
            continue
        if re.fullmatch(r"(?i)hw\d+", name):
            continue

        found[input_id] = HdmiSource(
            name=name,
            input_id=input_id,
            port=port,
            cec_label=cec or custom,
        )

    # Deduplicate by port: prefer custom/friendly labels over generic HDMI N
    by_port: dict[int, HdmiSource] = {}
    no_port: list[HdmiSource] = []
    for src in found.values():
        if src.port is None:
            no_port.append(src)
            continue
        existing = by_port.get(src.port)
        if existing is None:
            by_port[src.port] = src
            continue
        # Prefer non-generic name
        def _score(s: HdmiSource) -> int:
            n = s.name.casefold()
            if n.startswith("hdmi ") and n[5:].isdigit():
                return 0
            if s.cec_label:
                return 2
            return 1

        if _score(src) > _score(existing):
            by_port[src.port] = src

    # Also dedupe by exact name
    result: list[HdmiSource] = list(by_port.values()) + no_port
    seen_names: set[str] = set()
    unique: list[HdmiSource] = []
    for src in sorted(result, key=lambda s: (s.port is None, s.port or 0, s.name.lower())):
        key = src.name.casefold()
        if key in seen_names:
            continue
        seen_names.add(key)
        unique.append(src)
    return unique


def extract_media_metadata(dumpsys_media_session: str) -> MediaMetadata | None:
    """Best-effort parse of dumpsys media_session."""
    if not dumpsys_media_session:
        return None
    values: dict[str, str | None] = {}
    for field, patterns in METADATA_FIELD_PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(dumpsys_media_session)
            if match:
                values[field] = match.group("value").strip().strip("'\"")
                break
        else:
            values[field] = None
    if not any(values.values()):
        return None
    state_raw = values.get("playback_state")
    state = None
    if state_raw:
        digit = re.search(r"(\d+)", state_raw)
        state = PLAYBACK_STATE_NAMES.get(digit.group(1), state_raw) if digit else state_raw
    return MediaMetadata(
        title=values.get("title"),
        artist=values.get("artist"),
        album=values.get("album"),
        image_url=values.get("image_url"),
        playback_state=state,
    )


class AdbClient:
    """Thread-safe ADB client built on adb_shell (classic) / adb_shell_wifi (TLS).

    All methods block and must run in an executor thread.
    """

    def __init__(
        self,
        host: str,
        port: int = 5555,
        adbkey: str | None = None,
        *,
        use_tls: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.adbkey = adbkey
        self.use_tls = use_tls
        self._adb: Any | None = None
        self._lock = threading.RLock()
        self._hdmi_sources: list[HdmiSource] = []
        self._active_input: str | None = None
        self._media: MediaMetadata | None = None
        self._last_error: str | None = None
        self._status: str = "disconnected"
        self._custom_labels: dict[str, str] = {}

    @property
    def available(self) -> bool:
        return self._adb is not None

    @property
    def status(self) -> str:
        return self._status

    @property
    def hdmi_sources(self) -> list[HdmiSource]:
        return list(self._hdmi_sources)

    @property
    def active_input(self) -> str | None:
        return self._active_input

    @property
    def media(self) -> MediaMetadata | None:
        return self._media

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @staticmethod
    def _classify_error(err: BaseException | str) -> str:
        msg = str(err).lower()
        if "unauthorized" in msg or "not authorized" in msg:
            return "unauthorized"
        if "timed out" in msg or "timeout" in msg:
            return "timeout"
        if (
            "connection refused" in msg
            or "cannot connect" in msg
            or "no route" in msg
            or "unreachable" in msg
        ):
            return "offline"
        return "error"

    def _key_paths(self) -> tuple[Path, Path] | None:
        if not self.adbkey:
            return None
        priv = Path(self.adbkey)
        return priv, Path(f"{self.adbkey}.pub")

    def _load_signer(self) -> Any | None:
        """Load (creating if needed) the RSA key used for ADB auth."""
        from adb_shell.auth.keygen import keygen
        from adb_shell.auth.sign_pythonrsa import PythonRSASigner

        paths = self._key_paths()
        if paths is None:
            return None
        priv, pub = paths
        priv.parent.mkdir(parents=True, exist_ok=True)
        if not priv.exists() or not pub.exists():
            keygen(str(priv))
        return PythonRSASigner(
            pub.read_text(encoding="ascii"), priv.read_text(encoding="ascii")
        )

    def _open_device(self) -> Any:
        """Create and connect the transport for the configured mode."""
        signer = self._load_signer()
        kwargs: dict[str, Any] = {"auth_timeout_s": 20.0}
        if signer is not None:
            kwargs["rsa_keys"] = [signer]

        if self.use_tls:
            from adb_shell_wifi.adb_device import AdbDeviceTls

            device = AdbDeviceTls(
                self.host, self.port, default_transport_timeout_s=10.0
            )
            paths = self._key_paths()
            if paths is not None and paths[0].exists():
                kwargs["tls_priv_pem"] = paths[0].read_bytes()
        else:
            from adb_shell.adb_device import AdbDeviceTcp

            device = AdbDeviceTcp(
                self.host, self.port, default_transport_timeout_s=10.0
            )

        if not device.connect(**kwargs):
            raise ConnectionError(
                "ADB connect returned False (unauthorized? Accept the debugging "
                "prompt on the TV for Home Assistant)"
            )
        return device

    def connect(self) -> None:
        """Connect and verify a working shell. Raises ConnectionError on failure."""
        with self._lock:
            self.close()
            if self.port <= 0:
                self._status = "offline"
                self._last_error = "ADB connect port not known yet"
                raise ConnectionError(self._last_error)
            try:
                device = self._open_device()
                out = _to_text(device.shell("echo ha_adb_ok"))
                if "ha_adb_ok" not in out:
                    raise ConnectionError(
                        f"ADB connected but shell probe failed: {out!r}"
                    )
            except Exception as err:  # noqa: BLE001
                self._adb = None
                self._status = self._classify_error(err)
                self._last_error = f"{type(err).__name__}: {err}"
                _LOGGER.debug(
                    "ADB connect failed %s:%s (%s) → %s",
                    self.host,
                    self.port,
                    "tls" if self.use_tls else "classic",
                    self._last_error,
                )
                raise ConnectionError(self._last_error) from err

            self._adb = device
            self._status = "connected"
            self._last_error = None
            _LOGGER.info(
                "ADB connected to %s:%s (%s)",
                self.host,
                self.port,
                "tls" if self.use_tls else "classic",
            )

    def pair_wireless(self, pairing_port: int, pairing_code: str) -> bool:
        """Android 11+ TLS pairing via adb-shell-wifi.

        Generates the ADB key if missing, then performs the SPAKE2+TLS
        handshake against the pairing port shown on the TV.
        """
        code = pairing_code.strip().replace(" ", "")
        if not code.isdigit() or len(code) not in (6, 8):
            self._last_error = f"Invalid pairing code: {pairing_code!r}"
            self._status = "error"
            return False

        try:
            self._load_signer()
        except Exception as err:  # noqa: BLE001
            self._last_error = f"Could not load/create ADB key: {err}"
            self._status = "error"
            return False

        paths = self._key_paths()
        if paths is None or not paths[0].exists() or not paths[1].exists():
            self._last_error = "ADB key files missing after generation"
            self._status = "error"
            return False
        priv_path, pub_path = paths

        try:
            from adb_shell_wifi.pairing import PairingException, pair as wifi_pair
        except ImportError as err:
            self._last_error = (
                f"adb-shell-wifi import failed: {err}. "
                "Restart Home Assistant after installing the package."
            )
            self._status = "error"
            return False

        try:
            wifi_pair(
                host=self.host,
                port=int(pairing_port),
                pairing_code=code,
                private_key_pem=priv_path.read_bytes(),
                public_key=pub_path.read_bytes(),
                timeout_s=30.0,
            )
        except PairingException as err:
            msg = str(err)
            if "Connection refused" in msg or "Errno 111" in msg:
                self._last_error = (
                    "Connection refused — open a fresh Pair device with pairing "
                    "code on the TV and submit immediately."
                )
            else:
                self._last_error = f"Pairing failed: {msg}"
            self._status = "error"
        except Exception as err:  # noqa: BLE001
            self._last_error = f"{type(err).__name__}: {err}"
            self._status = self._classify_error(err)
        else:
            self._last_error = None
            self._status = "paired"
            _LOGGER.info("Wireless ADB paired with %s:%s", self.host, pairing_port)
            return True

        _LOGGER.warning(
            "Wireless pair failed %s:%s → %s",
            self.host,
            pairing_port,
            self._last_error,
        )
        return False

    def close(self) -> None:
        with self._lock:
            if self._adb is not None:
                try:
                    self._adb.close()
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Error closing ADB device", exc_info=True)
                self._adb = None
            if self._status == "connected":
                self._status = "disconnected"

    def shell(self, command: str) -> str | None:
        """Run a shell command. Returns None (and drops the session) on failure."""
        with self._lock:
            if self._adb is None:
                self._last_error = "ADB not connected"
                return None
            try:
                return _to_text(self._adb.shell(command))
            except Exception as err:  # noqa: BLE001
                self._last_error = f"{type(err).__name__}: {err}"
                self._status = self._classify_error(err)
                _LOGGER.debug(
                    "ADB shell failed [%s:%s] %s → %s",
                    self.host,
                    self.port,
                    command[:100],
                    self._last_error,
                )
                try:
                    self._adb.close()
                except Exception:  # noqa: BLE001
                    pass
                self._adb = None
                return None

    def refresh_state(self) -> None:
        """Refresh HDMI list, active input, and media metadata."""
        with self._lock:
            raw_labels = self.shell("settings get secure tv_input_custom_labels")
            self._custom_labels = parse_custom_labels(raw_labels)

            dumpsys = self.shell("dumpsys tv_input") or ""
            if dumpsys:
                self._hdmi_sources = extract_hdmi_sources(
                    dumpsys, self._custom_labels
                )
            self._active_input = extract_active_tv_input(dumpsys)
            if not self._active_input and dumpsys:
                # Fallback: look for state:1 on passthrough lines
                for match in INPUT_STATE_RE.finditer(dumpsys):
                    if match.group("state") == "1" and _looks_like_physical_input(
                        match.group("input_id")
                    ):
                        self._active_input = match.group("input_id")
                        break

            self._media = extract_media_metadata(
                self.shell("dumpsys media_session") or ""
            )
            _LOGGER.debug(
                "ADB refresh %s:%s — %d HDMI source(s), active=%s",
                self.host,
                self.port,
                len(self._hdmi_sources),
                self._active_input,
            )

    def refresh_hdmi(self) -> list[HdmiSource]:
        self.refresh_state()
        return self.hdmi_sources

    # TCL maps hdmi_port N → hardware id (14+N) on this generation
    _TCL_PORT_TO_HW = {1: 15, 2: 16, 3: 17, 4: 18}

    def _synthesize_tcl_source(self, port: int) -> HdmiSource | None:
        """Build an HdmiSource for HDMI port when discovery list is empty."""
        hw = self._TCL_PORT_TO_HW.get(port)
        if hw is None:
            return None
        input_id = f"com.tcl.tvinput/.TvPassThroughService/HW{hw}"
        for existing in self._hdmi_sources:
            if existing.input_id == input_id or existing.port == port:
                return existing
        return HdmiSource(name=f"HDMI {port}", input_id=input_id, port=port)

    def select_hdmi(self, source: HdmiSource) -> bool:
        """Switch to a physical input via ADB — try several TCL-compatible methods."""
        if not self.ensure_connected():
            _LOGGER.warning(
                "Cannot switch HDMI — ADB not connected (%s)", self._last_error
            )
            return False

        # Encoded URI first (works on current TCL firmware), then raw URI.
        # Quote styles differ because some shells double-escape.
        commands: list[str] = []
        for uri in (source.passthrough_uri, source.passthrough_uri_raw):
            commands.extend(
                (
                    f"am start -a android.intent.action.VIEW -d '{uri}' -f 0x10000000",
                    f'am start -a android.intent.action.VIEW -d "{uri}" -f 0x10000000',
                    f"am start -a android.intent.action.VIEW -d {uri} -f 0x10000000",
                )
            )

        last_result = None
        for cmd in commands:
            result = self.shell(cmd)
            last_result = result
            text = (result or "").strip()
            lower = text.lower()
            hard_fail = (
                result is None
                or "error:" in lower
                or "exception" in lower
                or "unable to resolve" in lower
                or "does not exist" in lower
            )
            # Success looks like "Starting: Intent { ... }" or
            # "Warning: Activity not started, intent has been delivered..."
            if not hard_fail and (
                "starting:" in lower
                or "intent has been delivered" in lower
                or "cmp=" in lower
                or text == ""
            ):
                _LOGGER.info(
                    "Switch input → %s (port=%s) via: %s", source.name, source.port, cmd
                )
                return True
            if result is None and not self.ensure_connected():
                break

        if source.port is not None:
            # Some firmwares accept this broadcast instead
            result = self.shell(
                "am broadcast -a tcl.tvinput.action.CHANGE_INPUT "
                f"--es input_id '{source.input_id}'"
            )
            if result is not None and "error" not in result.lower():
                _LOGGER.info("Switch input → %s via broadcast", source.name)
                return True

        self._last_error = (
            f"All HDMI switch methods failed for {source.name} "
            f"({source.input_id}). Last output: {(last_result or 'None')[:200]}"
        )
        _LOGGER.warning(self._last_error)
        return False

    def find_hdmi_source(self, name: str) -> HdmiSource | None:
        """Resolve a source name to an HdmiSource.

        Exact matches (name, CEC label, "HDMI N" alias) always win over partial
        ones, and a partial match is only used when it is unambiguous.
        """
        target = name.casefold().strip()
        if not self._hdmi_sources:
            self.refresh_hdmi()
        candidates = list(self._hdmi_sources)

        for src in candidates:
            if src.name.casefold() == target:
                return src
        for src in candidates:
            if src.cec_label and src.cec_label.casefold() == target:
                return src
        for src in candidates:
            if src.port is not None and target in {
                f"hdmi {src.port}",
                f"hdmi{src.port}",
            }:
                return src

        partial = [s for s in candidates if target and target in s.name.casefold()]
        if len(partial) == 1:
            return partial[0]

        if m := HDMI_NAME_RE.match(name.strip()):
            return self._synthesize_tcl_source(int(m.group(1)))
        return None

    def select_hdmi_by_name(self, name: str) -> bool:
        """Switch to the HDMI input matching name."""
        source = self.find_hdmi_source(name)
        if source is None:
            self._last_error = (
                f"No HDMI source matched '{name}' "
                f"(known: {[s.name for s in self._hdmi_sources]})"
            )
            _LOGGER.warning(self._last_error)
            return False
        return self.select_hdmi(source)

    def ping(self) -> bool:
        result = self.shell("echo ok")
        return bool(result and "ok" in result)

    def ensure_connected(self) -> bool:
        """Return True when a working session exists, reconnecting if needed."""
        with self._lock:
            if self._adb is not None and self.ping():
                self._status = "connected"
                return True
            try:
                self.connect()
            except ConnectionError:
                return False
            return True

    def keep_alive_tick(self) -> bool:
        """Keep the session authorized and refresh state. Returns availability."""
        if not self.ensure_connected():
            return False
        try:
            self.refresh_state()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("State refresh during keep-alive failed", exc_info=True)
        return self.available

    def current_source_name(self) -> str | None:
        """Resolve the active input id to a friendly HDMI name."""
        if not self._active_input:
            return None
        for hdmi in self._hdmi_sources:
            if hdmi.input_id == self._active_input or hdmi.input_id in self._active_input:
                return hdmi.name
        return None


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
