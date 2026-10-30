<p align="center">
  <img src="https://raw.githubusercontent.com/bisman-automations/ha-tcl-android-tv-remote/main/custom_components/tcl_android_tv_remote/brand/icon.png" alt="TCL Android TV Remote icon" width="128">
</p>

# TCL Android TV Remote

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.8%2B-blue.svg)](https://www.home-assistant.io/)
[![GitHub Release](https://img.shields.io/github/v/release/bisman-automations/ha-tcl-android-tv-remote)](https://github.com/bisman-automations/ha-tcl-android-tv-remote/releases)
[![Test](https://github.com/bisman-automations/ha-tcl-android-tv-remote/actions/workflows/test.yml/badge.svg)](https://github.com/bisman-automations/ha-tcl-android-tv-remote/actions/workflows/test.yml)
[![Validate](https://github.com/bisman-automations/ha-tcl-android-tv-remote/actions/workflows/validate.yml/badge.svg)](https://github.com/bisman-automations/ha-tcl-android-tv-remote/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/bisman-automations/ha-tcl-android-tv-remote)](LICENSE)

Custom Home Assistant integration for TCL Google TV / Android TV sets.

It uses the **Android TV Remote** protocol for power, volume, transport keys and app launching, and **ADB** for discovering and switching HDMI inputs — the part the core Android TV Remote integration can't do.

Domain: `tcl_android_tv_remote` · Requires Home Assistant 2026.8 or newer.

## Features

- Power, volume, play/pause and app launch over the Android TV Remote protocol
- HDMI input discovery with the names you set on the TV (or CEC device names), and switching between them
- One source list for HDMI inputs and your configured apps, on both the media player and a Source dropdown
- Rebuild or remove saved HDMI inputs after you change which device is plugged into a port
- Now-playing title / artist and playing / paused state from the TV's media session (via ADB)
- Wireless debugging (Android 11+) pairing during setup, or classic Network debugging on port 5555, or no ADB at all
- The Wireless debugging port is found automatically and re-found after the TV restarts
- Optional preset list of common TCL / Google TV apps

## Installation

Requires **Home Assistant 2026.8 or newer**.

### Marketplace (Home Assistant 2026.11 and newer)

[![Open your Home Assistant instance and open this repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=bisman-automations&repository=ha-tcl-android-tv-remote&category=integration)

1. Select the button above, or go to **Settings > Marketplace**, choose **Add from link**, enter `bisman-automations/ha-tcl-android-tv-remote` under **GitHub link**, and select **Add**. Adding a repository from a link needs a GitHub connection; the Marketplace asks you to connect one if you haven't.
2. Install **TCL Android TV Remote**. If a repair asks you to restart Home Assistant, restart it.

New versions show up under **Settings > Updates**. Already installed TCL Android TV Remote with HACS? There's nothing to do: Home Assistant moves it into the Marketplace the first time it starts on 2026.11.

### HACS (Home Assistant 2026.10 and older)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=bisman-automations&repository=ha-tcl-android-tv-remote&category=integration)

1. Click the button above, or in HACS open the menu, choose **Custom repositories**, and add `https://github.com/bisman-automations/ha-tcl-android-tv-remote` as an **Integration**.
2. Download **TCL Android TV Remote** and restart Home Assistant.

### Manual

Download `tcl_android_tv_remote.zip` from the [latest release](https://github.com/bisman-automations/ha-tcl-android-tv-remote/releases/latest), unzip it into `config/custom_components/tcl_android_tv_remote/`, and restart Home Assistant.

## Setup

[![Open your Home Assistant instance and start setting up TCL Android TV Remote.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=tcl_android_tv_remote)

1. Add the integration and enter the TV's IP address. TVs whose network name contains "TCL" are also discovered automatically.
2. Enter the PIN shown on the TV (Android TV Remote pairing).
3. Choose how HDMI control connects:
   - **Wireless debugging (recommended)** — on the TV open **Developer options → Wireless debugging → Pair device with pairing code**, then enter the pairing port and code. Submit right away; codes expire quickly. The connection port is optional: leave it blank and it is discovered.
   - **Network debugging on port 5555** — turn on Network debugging on the TV and accept the "Allow debugging" prompt (choose *Always allow*).
   - **Skip** — remote control and apps only, no HDMI inputs.

To enable Developer options, open **Settings → System → About** and press **Android TV OS build** seven times.

## Entities

| Entity | Purpose |
| --- | --- |
| Media player | Power, volume, transport, source list, now playing |
| Remote | Send key commands; launch apps as activities |
| Source (select) | HDMI inputs (with ADB) followed by configured apps |
| Home (button) | Send HOME |
| Current source (sensor) | Active HDMI input or app — ADB only |
| ADB (binary sensor, diagnostic) | ADB connected / disconnected, with a hint when it isn't — ADB only |
| ADB status (sensor, diagnostic, disabled by default) | connected / unauthorized / offline / timeout / error — ADB only |
| Refresh HDMI (button, diagnostic) | Rediscover HDMI inputs. Adds back an input you removed when the TV still reports it — ADB only |
| Rebuild sources (button, configuration) | Forget every saved HDMI input and custom name, then discover inputs again — ADB only |
| Find remote (button) | Sends `KEYCODE_PAIRING`; depending on the TV and remote this makes the remote chirp or opens remote pairing — ADB only |

When ADB goes offline, a repair issue explains what to check on the TV. It clears itself when ADB reconnects.

## Options

**Configure** opens a menu:

- **Settings** — IME (current-app detection), ADB on/off, ADB connection type and port, keep-alive interval
- **Applications** — add, rename, set icons for or delete apps; optionally add the TCL / Google TV presets
- **HDMI inputs** — remove inputs you no longer want on the source list, or rebuild the whole list after changing HDMI cables
- **Pair Wireless debugging** — pair (or re-pair) and switch to Wireless debugging

Use **Reconfigure** from the integration menu to change the TV's IP address, and re-pair the remote protocol from the repair prompt if the TV forgets Home Assistant.

## Actions (services)

| Action | Description |
| --- | --- |
| `tcl_android_tv_remote.refresh_hdmi` | Reconnect ADB if needed and rediscover HDMI inputs. Adds back an input you removed when the TV still reports it |
| `tcl_android_tv_remote.rebuild_sources` | Forget every saved HDMI input and custom name, then discover inputs again |
| `tcl_android_tv_remote.remove_hdmi_inputs` | Remove HDMI inputs by id or name. Refresh HDMI can add back what the TV still reports |
| `tcl_android_tv_remote.adb_command` | Admin only. Run a shell command on the TV and return its output |
| `tcl_android_tv_remote.adb_pair` | Admin only. Pair Wireless debugging (pairing port + code) and switch to it |

Each action needs a target (the TV's media player). Example:

```yaml
action: tcl_android_tv_remote.adb_command
target:
  entity_id: media_player.living_room_tv
data:
  command: dumpsys tv_input
response_variable: result
```

## Troubleshooting

- **ADB shows unauthorized** — in Developer options revoke debugging authorizations, reload the integration and accept the prompt on the TV.
- **HDMI inputs have generic names** — rename the inputs on the TV (Settings → Inputs), then press **Refresh HDMI**.
- **You moved an HDMI cable and the source list is wrong** — see below.
- **Download diagnostics** from the device page for the full ADB state and discovered inputs when reporting an issue.

### After you change HDMI cables

The TV remembers input names, and Home Assistant keeps the inputs it has already saved. After you plug a device into a different port, those names can point at the wrong port, and a port you unplugged can stay on the list.

1. On the device page, press **Rebuild sources** (under configuration). The same action is **Rebuild sources**, and **Configure → HDMI inputs** has a **Rebuild sources** switch. This clears every saved HDMI input and every custom name stored on the TV, then discovers the ports again.
2. To drop one port without clearing the rest, open **Configure → HDMI inputs**, select the inputs, and submit. Or run **Remove HDMI inputs** with their names (`HDMI 2`, `Apple TV`) or ids (`com.tcl.tvinput/.TvPassThroughService/HW15`). You can pass several at once. The media player source list and the Source dropdown update immediately, and an entity that belonged only to a removed input is removed.
3. Press **Refresh HDMI** afterwards if you want Home Assistant to add back any input the TV still reports. A removed input stays off the list until you do that (or rebuild). The regular connection check does not put it back.

### Diagnostics and debug logs

When something goes wrong, download diagnostics from **Settings → Devices & services → TCL Android TV Remote → ⋮ → Download diagnostics** and check the file before you share it.

For debug logs, use **Enable debug logging** on the integration page, or add this to `configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.tcl_android_tv_remote: debug
```

Then open an [issue](https://github.com/bisman-automations/ha-tcl-android-tv-remote/issues/new/choose) with the diagnostics, the log, and your Home Assistant and TCL Android TV Remote versions.

## Development

Tests run inside a real Home Assistant through
[pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component).
You need Python 3.14 for the current Home Assistant.

```bash
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
ruff check . && ruff format --check .
pytest
```

To test against the oldest supported Home Assistant (2026.8), use Python 3.14 and
`pip install -r requirements_test_min.txt` instead.

CI runs the same checks on every push and pull request, on both Home Assistant
versions, plus hassfest, HACS validation and the shared repo standards, using the
workflows in [bisman-automations/.github](https://github.com/bisman-automations/.github).
Releases are drafted from [CHANGELOG.md](CHANGELOG.md); see [CLAUDE.md](CLAUDE.md).

## Credits

Based on Home Assistant `androidtv_remote`, [androidtvremote2](https://github.com/tronikos/androidtvremote2), and ideas from [android-tv-bridge](https://github.com/Hyperion5088/homeassistant-android-tv-bridge).

## License

Apache-2.0. See [LICENSE](LICENSE).
