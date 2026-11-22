# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.10] - 2026-11-22

### Fixed

- **Diagnostics no longer show your TV's address in error messages.** The IP and MAC address were already hidden in the settings part of the file, but an ADB error such as "Connect call failed" still quoted the IP. They're now hidden everywhere in the file.
- **ADB shows as unknown, not disconnected, right after a restart.** The first ADB check runs in the background and can take up to half a minute. Until it finishes, the ADB sensor now shows unknown instead of a brief disconnect in its history.
- **The "ADB offline" repair goes away when you disable the integration.** It used to stay in Repairs until Home Assistant restarted, even though nothing was checking ADB any more.

## [1.1.9] - 2026-11-20

### Fixed

- **Tests are steady on the upcoming Home Assistant 2026.12.** A few settings, reconfigure and re-pairing tests finished before the reload they start had run, which failed now and then against Home Assistant 2026.12's development build. They now wait for it. Nothing changes for you.

### Changed

- **Test tools updated.** Ruff 0.17.6, and the tests use androidtvremote2 0.3.3 and spake2-cffi 1.0.1. androidtvremote2 0.3.3 fixes text sent to TCL TVs arriving out of order or not at all. Home Assistant 2026.12 is set to include it, so that fix reaches you when you update Home Assistant.

## [1.1.8] - 2026-11-15

### Fixed

- **Passes Home Assistant's checks again.** 1.1.7 also listed pyOpenSSL as a requirement. Home Assistant already includes it and doesn't allow integrations to list it, so it's gone again. Pairing with a code still gets what it needs.

## [1.1.7] - 2026-11-15

### Fixed

- **Wireless debugging pairing with a code works after updating.** 1.1.6 didn't fix "No module named 'spake2'" for anyone updating from an earlier version: Home Assistant saw the ADB library was already installed and skipped the extra part pairing needs. The missing library is now installed by its own name. Update, restart Home Assistant, then pair again.

## [1.1.6] - 2026-11-14

### Changed

- **Renaming an entity keeps it running.** From Home Assistant 2026.11, when you change one of this integration's entity IDs, the entity moves to its new ID in place instead of being removed and added again, as Home Assistant now expects. Everything keeps working the same.

### Fixed

- **Wireless debugging pairing with a code works.** Pairing with a pairing code failed with "No module named 'spake2'" because Home Assistant didn't install the two libraries pairing needs. They're now installed with the integration, so pair again after updating and restarting Home Assistant.

## [1.1.5] - 2026-11-13

### Fixed

- **ADB updates belong to their TV's entry.** The ADB connection's updates are tied to its TV in Home Assistant, as Home Assistant expects. Nothing changes for you.

## [1.1.4] - 2026-11-10

### Changed

- **Install from the Marketplace by searching for TCL Android TV Remote.** Home Assistant 2026.11 renames HACS to the Marketplace, so the install steps start by searching the Marketplace. Searching HACS stays for Home Assistant 2026.10 and older, and adding the repository as a custom repository remains the fallback.
- **Ruff 0.17.4.** Linting uses the current Ruff release.

## [1.1.3] - 2026-11-04

### Changed

- **HACS install.** The README now leads with searching for TCL Android TV Remote in HACS. Adding the GitHub repository as a custom repository stays as the fallback, and the button that opens the repository in HACS stays.

## [1.1.2] - 2026-11-04

### Fixed

- **Removing an HDMI input no longer clears every custom name on the TV.** The names are read from the TV immediately before they are written. Only the inputs you removed lose their names, including a name changed on the TV since the last refresh. If that read fails (for example the TV is in standby and the names were never loaded), nothing is written and the names stay. The setting is deleted only when the input you removed was the last one with a custom name. Rebuild sources follows the same rule: it deletes the names only after reading them, and leaves them unchanged when the read fails.

### Removed

- **Find remote button.** It sent `KEYCODE_PAIRING`, which can open remote pairing instead of making the remote chirp, and that was not confirmed on TCL TVs. The button is no longer created. An install that already has it drops that button entity the next time the integration loads. Home, Refresh HDMI, and Rebuild sources stay.

## [1.1.1] - 2026-10-30

### Changed

- **Install from the Marketplace.** The README now explains how to install from the Marketplace that replaces HACS in Home Assistant 2026.11, with its own button. The HACS steps stay for Home Assistant 2026.10 and older, and an install you already have moves over by itself.

## [1.1.0] - 2026-10-30

### Changed

- **Requires Home Assistant 2026.8 or newer.**
- The integration's dark-mode icon now comes in both sizes, and the large icon is full size.

### Fixed

- **Typing a channel number while another is still being typed** no longer makes the first action fail as cancelled: the newer number replaces it, and the first action finishes quietly.
- Unloading or restarting the integration stops a channel number that's still being typed.

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

[1.1.10]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.1.9...v1.1.10
[1.1.9]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.1.8...v1.1.9
[1.1.8]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.1.7...v1.1.8
[1.1.7]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.1.6...v1.1.7
[1.1.6]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.1.5...v1.1.6
[1.1.5]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.1.4...v1.1.5
[1.1.4]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.1.3...v1.1.4
[1.1.3]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.0.3...v1.1.0
[1.0.3]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/bisman-automations/ha-tcl-android-tv-remote/releases/tag/v1.0.0
