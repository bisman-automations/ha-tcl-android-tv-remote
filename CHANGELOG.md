# Changelog

All notable changes to the **ha-tcl-android-tv-remote** Home Assistant integration will be documented in this file.

## [1.0.0] - 2026-10-23

### Remote control
* **Android TV Remote protocol:** power, volume, playback keys and app launching, with media player and remote entities.
* **Current app:** shown on the media player and as the source when IME is enabled.

### HDMI inputs
* **Discovery:** HDMI inputs are found over ADB and named from the TV's input labels or the connected CEC device.
* **Switching:** pick an input from the media player or the Source dropdown. HDMI inputs and configured apps share one source list.
* **Now playing:** title, artist and playing / paused state from the TV's media session while the TV is on.

### ADB connection
* **Setup choices:** pair Wireless debugging (Android 11+), use Network debugging on port 5555, or skip HDMI control.
* **Automatic port:** the Wireless debugging port is discovered and re-discovered when the TV picks a new one after a restart.
* **Repairs:** a repair issue explains what to check while ADB is offline and clears itself when it reconnects.

### Actions
* `refresh_hdmi` rediscovers HDMI inputs.
* `adb_command` runs a shell command and returns its output (admin only).
* `adb_pair` pairs Wireless debugging and switches to it (admin only).

### Other
* Optional preset list of common TCL / Google TV apps.
* Diagnostics download with the host and MAC redacted.
* Discovery only offers TVs that identify as TCL.
* Minimum Home Assistant version: 2025.8.0.
