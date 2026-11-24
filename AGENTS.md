# Notes for AI agents

An e-paper calendar: a Raspberry Pi Zero W/WH drives a Waveshare 7.3" (F)
panel, showing events from iCalendar feeds and the weather. Read
[README.md](README.md) for what it does, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for how the code is split, and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for
everything about installing it.

## Common tasks

| Task | Where |
|---|---|
| Make a new SD card | [docs/DEPLOYMENT.md → Set up a new display](docs/DEPLOYMENT.md#set-up-a-new-display): Imager, then `deploy/sdcard/prepare.sh`, then boot |
| Card for unreleased code | `venv/bin/python -m gcal_epd.build_release`, then `prepare.sh --bundle dist/<label>/*-sdcard.zip` |
| Publish a release | [docs/DEPLOYMENT.md → Publish a release](docs/DEPLOYMENT.md#publish-a-release): bump `pyproject.toml`, tag `vX.Y.Z`, the maintainer signs on their Mac |
| Update a running display | Automatic, before each refresh, if installed as a release; by hand: [docs/DEPLOYMENT.md → Update a running display](docs/DEPLOYMENT.md#update-a-running-display) |
| See a display's update state | on the Pi: `sudo env PYTHONPATH=/opt/e-pages/current/src python3 -m gcal_epd.releases status` |
| Run the tests | `venv/bin/python -m pytest -q` (CI: Python 3.11 and 3.13) |
| Render without a panel | `venv/bin/python -m gcal_epd.main` writes `preview.png` |

## Rules

- **Calendar feed URLs are secrets.** `ics_feeds.toml` (and
  `ics_feeds.pending.toml`) hold bearer tokens to private calendars: never
  commit, print, log or paste them, on the Mac or the Pi.
- **Never store or repeat passwords or keys** a person gives you (the Pi's
  sudo password, the release signing key). Ask again when needed.
- Release signing keys: an everyday key on the maintainer's Mac and an
  offline backup key, both listed in `deploy/release/allowed_signers`. Do
  not generate, move or replace keys, or put one into CI; key rotation is
  the maintainer's call (docs/DEPLOYMENT.md, "When a key is lost or leaked").
- Pull requests target `develop`. One refactor or feature per branch. Ask
  before force-pushing.
- Docs exist in English and Traditional Chinese (`*.zh-TW.md`). English is
  the source; change both. `tests/docs/test_translations.py` checks they keep
  the same headings, tables and diagrams.
- `deploy/*.sh` and `deploy/*/*.sh` must pass `shellcheck --severity=warning`.
- Code that runs before a release's venv exists (`gcal_epd.releases`,
  `infrastructure/release/`, `build_release`) uses the standard library only.

## Working with a display

- A display is usually reachable as `ssh <user>@<hostname>.local` (e.g.
  `admin@epaper.local`) when SSH was enabled in Imager. `sudo` asks for the
  user's password.
- An installed display runs from `/opt/e-pages/current`; its own files are
  in `/opt/e-pages/data/`. Logs: `journalctl -u gcal-epd -u epd-wifi-setup
  -u epd-feed-setup`.
- First-boot problems: `epd-firstboot.log` on the card's boot partition,
  readable from the Mac with the card plugged in.
- A display with PiSugar power management may power itself off after each
  refresh; an open SSH session keeps it on.
- A new card ships pisugar-server (PiSugar 3, 127.0.0.1 only, no web page;
  see deploy/sdcard/firstboot.sh). Never switch its web page on or listen
  on 0.0.0.0: anyone on the network could power the Pi off. An update
  check runs before every refresh of gcal-epd.service (it Wants=
  epd-update.service, ordered Before= it; no timer); the power manager
  waits while the check or the refresh runs, and up to 5 min while one is
  queued (power_policy.QUEUE_WAIT). Run-time limits (TimeoutStartSec, from
  each unit's own start): epd-update 15 min (stopped: back to the running
  release, one failed try), gcal-epd 3 min, epd-power's setup 2 min,
  epd-button@ 3 min.
- The PiSugar's custom button: pisugar-server (root) only runs
  `systemctl start --no-block epd-button@<action>.service`
  (gcal_epd.buttons; set up by `power_manager buttons`). Every push to the
  panel takes `DATA_DIR/panel.lock` (infrastructure/panel_lock.py).
  Single press: privacy page on/off (`DATA_DIR/display_mode.toml`; an
  unreadable file means privacy; no events are fetched while it is on).
  The switch takes the panel lock too, and a refresh rechecks the mode
  under it before drawing, so a calendar fetched before a press is never
  drawn after it. A feed checks it again before logging its name.
  Double press: redraw what is showing.
