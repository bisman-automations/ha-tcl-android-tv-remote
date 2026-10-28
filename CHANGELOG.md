# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.3] - 2026-10-26

### Added

- **Rebuild sources** forgets every saved HDMI input and the custom names stored on the TV, then discovers inputs again. Use it after moving HDMI cables. It is a configuration button, an action, and a switch under Configure → HDMI inputs.
- **Remove HDMI inputs** drops the inputs you choose from the source list and deletes their custom names. Configure → HDMI inputs has a multi-select, and the action takes input ids or names. Refresh HDMI adds back any input the TV still reports.

### Changed

- The README follows the same layout as the other bisman-automations integrations: a button that opens it in HACS, a button that starts setup, and troubleshooting steps for debug logs and diagnostics.
- The changelog no longer keeps an Unreleased section, and the agent notes follow the updated shared release rules.

## [1.0.2] - 2026-10-23

### Changed

- Tests run on Python 3.13 and 3.14, so they cover the newest Home Assistant release as well as older ones.

### Fixed

- **Home Assistant 2026.10:** the integration failed to load ("Not loaded", and the config flow showed "Invalid handler specified") because a Home Assistant helper it used for actions moved. It now works on 2026.10 and older versions.

## [1.0.1] - 2026-10-23

### Added

- Tests for reauthentication, reconfiguring the IP address, Wireless debugging port discovery and the option migration.
- Dependabot keeps the GitHub Actions versions up to date.

### Changed

- **Option cleanup:** entries from pre-release builds drop the unused parental-lock options, and the ADB connection type is now stored instead of guessed from the port.

## [1.0.0] - 2026-10-23

### Added

- **Remote control**
  - **Android TV Remote protocol:** power, volume, playback keys and app launching, with media player and remote entities.
  - **Current app:** shown on the media player and as the source when IME is enabled.
- **HDMI inputs**
  - **Discovery:** HDMI inputs are found over ADB and named from the TV's input labels or the connected CEC device.
  - **Switching:** pick an input from the media player or the Source dropdown. HDMI inputs and configured apps share one source list.
  - **Now playing:** title, artist and playing / paused state from the TV's media session while the TV is on.
- **ADB connection**
  - **Setup choices:** pair Wireless debugging (Android 11+), use Network debugging on port 5555, or skip HDMI control.
  - **Automatic port:** the Wireless debugging port is discovered and re-discovered when the TV picks a new one after a restart.
  - **Repairs:** a repair issue explains what to check while ADB is offline and clears itself when it reconnects.
- **Actions**
  - `refresh_hdmi` rediscovers HDMI inputs.
  - `adb_command` runs a shell command and returns its output (admin only).
  - `adb_pair` pairs Wireless debugging and switches to it (admin only).
- **Other**
  - Optional preset list of common TCL / Google TV apps.
  - Diagnostics download with the host and MAC redacted.
  - Discovery only offers TVs that identify as TCL.
  - Minimum Home Assistant version: 2025.8.0.

[1.0.3]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/releases/tag/v1.0.0
