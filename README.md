# TCL Android TV Remote

Custom Home Assistant integration for TCL Google TV / Android TV sets.

It uses the **Android TV Remote** protocol for power, volume, transport keys and app launching, and **ADB** for discovering and switching HDMI inputs — the part the core Android TV Remote integration can't do.

Domain: `tcl_android_tv_remote` · Requires Home Assistant 2025.8 or newer.

## Features

- Power, volume, play/pause and app launch over the Android TV Remote protocol
- HDMI input discovery with the names you set on the TV (or CEC device names), and switching between them
- One source list for HDMI inputs and your configured apps, on both the media player and a Source dropdown
- Now-playing title / artist and playing / paused state from the TV's media session (via ADB)
- Wireless debugging (Android 11+) pairing during setup, or classic Network debugging on port 5555, or no ADB at all
- The Wireless debugging port is found automatically and re-found after the TV restarts
- Optional preset list of common TCL / Google TV apps

## Install

### HACS

1. Add this repository as a HACS custom repository (type: Integration)
2. Install **TCL Android TV Remote**
3. Restart Home Assistant

### Manual

1. Copy `custom_components/tcl_android_tv_remote` into `config/custom_components/`
2. Restart Home Assistant

## Setup

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
| Refresh HDMI (button, diagnostic) | Rediscover HDMI inputs — ADB only |
| Find remote (button) | Sends `KEYCODE_PAIRING`; depending on the TV and remote this makes the remote chirp or opens remote pairing — ADB only |

When ADB goes offline, a repair issue explains what to check on the TV. It clears itself when ADB reconnects.

## Options

**Configure** opens a menu:

- **Settings** — IME (current-app detection), ADB on/off, ADB connection type and port, keep-alive interval
- **Applications** — add, rename, set icons for or delete apps; optionally add the TCL / Google TV presets
- **Pair Wireless debugging** — pair (or re-pair) and switch to Wireless debugging

Use **Reconfigure** from the integration menu to change the TV's IP address, and re-pair the remote protocol from the repair prompt if the TV forgets Home Assistant.

## Actions (services)

| Action | Description |
| --- | --- |
| `tcl_android_tv_remote.refresh_hdmi` | Reconnect ADB if needed and rediscover HDMI inputs |
| `tcl_android_tv_remote.adb_command` | Admin only. Run a shell command on the TV and return its output |
| `tcl_android_tv_remote.adb_pair` | Admin only. Pair Wireless debugging (pairing port + code) and switch to it |

All three need a target (the TV's media player). Example:

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
- **Download diagnostics** from the device page for the full ADB state and discovered inputs when reporting an issue.

## Credits

Based on Home Assistant `androidtv_remote`, [androidtvremote2](https://github.com/tronikos/androidtvremote2), and ideas from [android-tv-bridge](https://github.com/Hyperion5088/homeassistant-android-tv-bridge).

## License

Apache-2.0
