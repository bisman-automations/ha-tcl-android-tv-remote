"""Constants for the TCL Android TV Remote integration."""

from typing import Final

DOMAIN: Final = "tcl_android_tv_remote"

CONF_APPS: Final = "apps"
CONF_ENABLE_IME: Final = "enable_ime"
CONF_ENABLE_IME_DEFAULT_VALUE: Final = True
CONF_APP_NAME: Final = "app_name"
CONF_APP_ICON: Final = "app_icon"

# ADB / HDMI
CONF_ENABLE_ADB: Final = "enable_adb"
CONF_ENABLE_ADB_DEFAULT: Final = True
CONF_ADB_PORT: Final = "adb_port"
CONF_ADB_PORT_DEFAULT: Final = 5555
CONF_ADB_MODE: Final = "adb_mode"
ADB_MODE_TLS: Final = "tls"  # Android 11+ Wireless debugging (paired, random port)
ADB_MODE_CLASSIC: Final = "classic"  # Network debugging, usually port 5555
# 0 means "not known yet": discover the TLS connect port via mDNS
ADB_PORT_DISCOVER: Final = 0
CONF_KEEPALIVE_INTERVAL: Final = "keepalive_interval"
CONF_KEEPALIVE_INTERVAL_DEFAULT: Final = 60
KEEPALIVE_INTERVAL_MIN: Final = 15
KEEPALIVE_INTERVAL_MAX: Final = 600

# Saved HDMI inputs (options). Absent until the user rebuilds, removes or refreshes.
CONF_HDMI_INPUTS: Final = "hdmi_inputs"
CONF_HDMI_REMOVED: Final = "hdmi_removed"

# Services
SERVICE_REFRESH_HDMI: Final = "refresh_hdmi"
SERVICE_REBUILD_SOURCES: Final = "rebuild_sources"
SERVICE_REMOVE_HDMI_INPUTS: Final = "remove_hdmi_inputs"
SERVICE_ADB_COMMAND: Final = "adb_command"
SERVICE_ADB_PAIR: Final = "adb_pair"
ATTR_COMMAND: Final = "command"
ATTR_INPUTS: Final = "inputs"
ATTR_PAIRING_PORT: Final = "pairing_port"
ATTR_PAIRING_CODE: Final = "pairing_code"

# Fallback HDMI labels shown when ADB is up but discovery returned nothing yet
GENERIC_HDMI_SOURCES: Final = ("HDMI 1", "HDMI 2", "HDMI 3", "HDMI 4")

# Default TCL / Google TV app presets (package -> friendly name)
DEFAULT_TCL_APPS: Final[dict[str, str]] = {
    "com.netflix.ninja": "Netflix",
    "com.google.android.youtube.tv": "YouTube",
    "com.disney.disneyplus": "Disney+",
    "com.amazon.amazonvideo.livingroom": "Prime Video",
    "com.hulu.livingroomplus": "Hulu",
    "com.plexapp.android": "Plex",
    "com.spotify.tv.android": "Spotify",
    "com.google.android.videos": "Google TV",
    "com.apple.atve.androidtv.appletv": "Apple TV",
    "com.wbd.stream": "Max",
}
