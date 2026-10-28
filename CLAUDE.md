# TCL Android TV Remote: notes for Claude and other coding agents

TCL Android TV Remote (`custom_components/tcl_android_tv_remote`, domain
`tcl_android_tv_remote`) is a HACS custom integration for TCL (and other)
Android/Google TVs. It controls the TV through the Android TV Remote protocol
(`androidtvremote2`) and, optionally, ADB (`adb-shell`, `adb-shell-wifi`) for
HDMI input names, media details and source switching.

Oldest supported Home Assistant: `hacs.json` → `homeassistant` (2025.8.0).

## Layout

| Path | What it is |
| --- | --- |
| `__init__.py` | Setup: the remote connection, the optional ADB coordinator, platforms, services. |
| `config_flow.py` | Setup (manual or zeroconf `_androidtvremote2._tcp`), remote pairing, ADB setup (wireless debugging pairing, classic, or none), reauth, reconfigure. Options: settings and per-app entries. |
| `adb.py` | ADB helpers: HDMI inputs with CEC labels, media metadata, and shell access behind a lock (one command at a time). |
| `coordinator.py` | ADB keep-alive, TLS port tracking, HDMI and media refresh. |
| `sources.py` | Source handling shared by the media player and the source select. |
| `helpers.py` | Shared helpers, including the ADB key path (`.storage/tcl_android_tv_remote_adbkey`). |
| `media_player.py`, `remote.py`, `select.py`, `sensor.py`, `binary_sensor.py`, `button.py`, `entity.py` | Entities. |
| `services.py`, `services.yaml` | Actions. |
| `diagnostics.py` | Config entry diagnostics. |
| `strings.json` + `translations/en.json` | Must stay identical. |

## Conventions

- ADB is optional. Every feature must degrade cleanly when ADB is off or the
  TV refuses it; the remote protocol alone must keep working.
- The ADB key in `.storage` is a credential. Never log it or include it in
  diagnostics.
- Don't block the event loop: ADB calls are synchronous and run in the
  executor, under the lock in `adb.py`.
- Parse `dumpsys` output with the patterns in `adb.py`; TCL firmware prints
  extra lines and formats that stock Android doesn't. Add the raw output
  you're handling to `tests/test_adb_parse.py`.
- Don't change entity unique IDs; automations depend on them.

## Checks

Run the shared checks at the end of this file, on the newest Home Assistant
(`requirements_test.txt`, Python 3.14) and the oldest supported one
(`requirements_test_min.txt`, Python 3.13). CI runs both.

The tests need the integration's runtime requirements; both requirements
files include them. Add a test for every behavior change.

## Docs

- Update `README.md` when entities, options or actions change.
- `LICENSE` is the Apache License 2.0. Credits for the projects this builds
  on are in the README.

<!-- BEGIN bisman-automations shared rules -->
<!-- This block is the same in every bisman-automations repo. Edit it in
     bisman-automations/.github (templates/CLAUDE.shared.md) and copy it to
     every repo; the Validate workflow's "standards" job checks it matches. -->

## Shared rules (every bisman-automations repo)

### Releases

- The version lives in `custom_components/<domain>/manifest.json`. Anything
  else that repeats it is called out in the repo-specific notes below and is
  bumped in the same commit.
- Versions follow [Semantic Versioning](https://semver.org): patch for fixes,
  translations, docs and CI; minor for new features, options or entities;
  major when something users rely on is removed or renamed (entities,
  services, events, options) or setup has to be redone.
- Check what is released before choosing a version:
  `git ls-remote --tags origin | awk -F/ '{print $3}' | sort -V | tail -1`
  (`sort -V`: plain sorting puts `v1.10.0` before `v1.9.0`). Never add
  changes to a released version. If the manifest version has no tag yet,
  add to its CHANGELOG section instead of bumping again.
- Every push to `main` ships as a release. In that same commit, named
  `Release X.Y.Z`, bump the manifest version and write the notes directly
  under a new `## [X.Y.Z] - YYYY-MM-DD` heading in `CHANGELOG.md` (Keep a
  Changelog: Added, Changed, Deprecated, Removed, Fixed, Security), with
  that version's compare link at the bottom. There is no `## [Unreleased]`
  section and no `[Unreleased]:` compare link. New work is not collected
  under a holding heading and moved later; the release commit is where the
  heading and the entries are written. The standards check fails if a
  `## [Unreleased]` heading is present.
- Ask Donavan before every push. Push fast-forward only: never force-push,
  rebase or amend anything already pushed, or rewrite history in any other
  way. Rewriting history orphans the release tags (it broke drafting in
  ha-button-actions).
- Pushing to `main` runs **Draft release**, which creates or refreshes a
  draft `vX.Y.Z` with that version's CHANGELOG section as the notes, the
  commits since the last release and `<domain>.zip`. **Donavan publishes
  the draft himself**, and publishing creates the tag. Never create or push
  tags, publish releases, or edit published releases.
- Publishing runs **Release check**: the tag must match the manifest version
  and the CHANGELOG, and be on `main`. If it fails, fix it with a new patch
  release, not by moving the tag.

### Commits

- Author commits as `Donavan Becker <donavan.becker@icloud.com>` (set
  `git config user.name` / `user.email` in the clone). HACS's
  default-repository check needs the submitter to have a fair share of the
  commits. Credit an AI assistant with a `Co-Authored-By:` trailer if you
  like, never as the author.
- Subject lines are plain, imperative and say what changed for the user
  ("Show Pico remotes as unavailable when Lutron isn't running"). No
  `fix:`/`feat:` prefixes. Release commits are "Release X.Y.Z".
- Commit and push only when asked.

### CI (shared workflows)

- `.github/workflows/` holds four thin callers of the reusable workflows in
  [bisman-automations/.github](https://github.com/bisman-automations/.github):
  `test.yml` (lint, frontend, pytest on the oldest supported and the newest
  Home Assistant, plus the upcoming one as information only), `validate.yml`
  (hassfest, HACS, standards), `draft-release.yml` and `release-check.yml`.
  Don't add jobs to the callers. Use the shared workflow's inputs, or change
  the shared workflow so every repo gets the improvement.
- `requirements_test.txt` leaves `pytest-homeassistant-custom-component`
  unpinned (newest Home Assistant) and pins ruff (and mypy where used).
  `requirements_test_min.txt` pins the harness release for the minimum in
  `hacs.json`: the newest harness release of that month. CI fails if they
  drift apart.
- Raising the minimum Home Assistant means changing, together: `hacs.json`,
  `requirements_test_min.txt`, `python-min` in `test.yml` (3.13 up to
  2026.2, 3.14 from 2026.3), the README's Home Assistant badge, and a
  CHANGELOG entry.
- Home Assistant 2026.3 and newer need Python 3.14 (3.14.2+).
- The published hassfest rejects `categories` in `manifest.json` and Pillow
  in `requirements`. Leave both out.
- Dependabot (`.github/dependabot.yml`) proposes action and pinned-tool
  updates weekly. It ignores the test harness on purpose.
- Test and Validate also run every Thursday, the day after Home Assistant's
  betas come out. The **next** test job (newest pre-release harness) is
  information only: when it fails, fix the cause before that release ships.

### Before saying work is done

Run from the repo root, in a Python 3.14 venv with `requirements_test.txt`
installed:

```
ruff check .
ruff format --check .
pytest
```

Also run `node --test tests/*.mjs` when the repo has Node tests, mypy when
the repo-specific notes list it, and the tests in a second venv with
`requirements_test_min.txt` when a change could behave differently on the
oldest supported Home Assistant. The standards check (also in CI) is
`python <path to bisman-automations/.github>/scripts/check_repo.py .`.

### Code and docs

- Support every Home Assistant from the `hacs.json` minimum to the newest
  release. Check for deprecations in the newest release and the beta.
- Keep entity IDs, unique IDs, service names and event names stable. When
  one has to change, migrate it and say so under Changed in the CHANGELOG.
- `strings.json` and `translations/en.json` hold the same keys. Home
  Assistant reads only `translations/`, so change both in the same commit.
- Never put personal details in the repo (README, CHANGELOG, code, tests,
  screenshots): no names, addresses, account or device identifiers, or real
  entity IDs. Use placeholders such as `light.living_room`.
- `README.md` is user documentation with the standard header (badges, HACS
  and "add integration" My buttons) and sections Installation, Setup, ...,
  Troubleshooting, Development, License. Use plain language and show names,
  not entity IDs, wherever the UI does.
<!-- END bisman-automations shared rules -->
