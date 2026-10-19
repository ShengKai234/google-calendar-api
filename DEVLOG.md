# Development Log

Chronological record of decisions, discussions, and changes made to this project.

---

## 2026-07-05

### 2026-07-05 00:11 CST — Credential file audit & .gitignore fix

**Discussion:**
Reviewed all untracked files shown by `git status`. Found that `credentials.json` and `service_account.json` were silently not ignored by git due to a missing newline in `.gitignore` — the last entry was literally `credentials.jsonservice_account.json` on a single line, so neither pattern matched.

**Findings:**
- `service_account.json` — actively used by `src/gcal_epd/auth.py` and `config.toml`. Must stay on disk but must not be committed.
- `credentials.json` — OAuth 2.0 Desktop client file (`installed` key). Not referenced by any current Python source. Leftover from an older OAuth flow.
- `client_secret_*.json` (×2) — OAuth client secrets. Not referenced anywhere in current code. Also leftover from the old OAuth flow.
- `token.json` — OAuth token cache. Not used in current code. Already correctly ignored on its own line.

**Decisions:**
- Fix `.gitignore`: split `credentials.jsonservice_account.json` into two separate lines.
- Delete `credentials.json` and both `client_secret_*.json` files — unused, risk of accidental exposure.
- Keep `service_account.json` on disk (required for the app), now properly gitignored.

**Changes made:**
- `.gitignore` line 171: split into `credentials.json` and `service_account.json` on separate lines.
- Deleted: `credentials.json`
- Deleted: `client_secret_518162094836-nl1h6d7rg14vidoeo4stb5s8jfh64f1u.apps.googleusercontent.com.json`
- Deleted: `client_secret_962456056188-hdphgp0kkeglngrivv49oagpglp22b2b.apps.googleusercontent.com.json`

---

### 2026-07-05 00:11 CST — Auth flow review

**Discussion:**
Reviewed the current authentication mechanism to understand how the app accesses Google Calendar.

**Summary:**
The app uses a **Google Service Account** (not user OAuth). Auth flow:

1. `service_account.json` holds a private key — loaded by `auth.py:get_credentials()`.
2. On first run (`--setup`), the service account email is shown to the user (terminal + QR code + optional e-paper screen).
3. User manually shares their Google Calendar with that email in Google Calendar settings.
4. App polls every 30s (up to 10 min) via `calendar_client.check_calendar_access()` until access is confirmed.
5. On success, the user's email is saved as `calendar_ids` in `config.toml`.
6. All subsequent runs load credentials from `service_account.json` and call the API directly — no user interaction needed.

The old `credentials.json` / `client_secret_*.json` / `token.json` files were artifacts of a previous OAuth 2.0 user-consent flow that has been replaced by service account auth.

---

### 2026-07-05 01:48 CST — DDD refactor with Repository pattern

**Discussion:**
Decided to restructure the codebase using light DDD layering to support future data sources beyond Google Calendar (weather, news, etc.). Key design decisions made:

- Keep package name `gcal_epd` as-is.
- Use `typing.Protocol` (PEP 544) instead of ABC for repository interfaces — structural subtyping means implementations need no inheritance, and type checkers enforce the contract at dev time. Added `@runtime_checkable` to both Protocols to preserve `isinstance()` support.
- Weather source: use Open-Meteo (free, no API key required). First additional source.
- Display layout: calendar events keep the full main area; weather appears as a widget on the right side of the header bar (temperature + condition + humidity).
- Config: migrated from flat `[auth]` / `[calendar]` sections to `[[sources]]` array, allowing multiple sources of any type.
- Setup flow (QR code + polling) kept for Google Calendar only; other sources (Open-Meteo) are config-only.

**New structure:**
```
src/gcal_epd/
├── domain/
│   ├── event.py            # CalendarEvent dataclass
│   ├── weather.py          # WeatherInfo dataclass
│   └── repositories.py     # EventRepository + WeatherRepository (typing.Protocol)
├── infrastructure/
│   ├── google_calendar/
│   │   ├── auth.py         # service account auth (moved from root)
│   │   ├── repository.py   # GoogleCalendarRepository
│   │   └── setup.py        # one-time setup flow (moved from root)
│   └── open_meteo/
│       └── repository.py   # OpenMeteoRepository
├── application/
│   └── display_service.py  # orchestrates fetch → render → display
├── render/
│   ├── draw.py             # updated: weather widget in header
│   └── layout.py           # updated: import from domain.event
├── epd.py                  # unchanged
└── main.py                 # full rewrite: reads [[sources]], builds repos
```

**Files deleted:** `auth.py`, `calendar_client.py`, `setup.py` (all at gcal_epd root — content moved into layers above).

**config.toml migrated to:**
```toml
[[sources]]
type = "google_calendar"
calendar_ids = [...]
service_account_file = "service_account.json"
days_ahead = 14
max_results_per_calendar = 100

[[sources]]
type = "open_meteo"
latitude = 25.0330
longitude = 121.5654
location = "Taipei"

[display]
output_path = "preview.png"
font_path = "..."
```

**To add a new source in the future:**
1. Add a class under `infrastructure/` satisfying the relevant Protocol.
2. Add a `[[sources]]` block in `config.toml`.
3. Wire it up in `main.py`'s builder functions.

**Tests:** 68 tests added under `tests/` covering all layers (domain, infrastructure, application, render). All pass.

---

## 2026-08-30

### 2026-08-30 — Dark-theme UI redesign

**Discussion:**
Redesigned the panel from a reference mockup: dark theme, bordered header
card, three-column event table with underlined titles.

**Decisions:**
- Flat `EventRow` list replaces the `DayBlock` label model — the design
  repeats the date on every row rather than using day headers. Days still
  group, which is what produces the vertical gap between them.
- Dropped per-calendar accent colours and the calendar-name subtitle; the
  reference shows neither. Calendar attribution is no longer visible.
- No greys available on the 7-colour panel, so hierarchy comes from size
  and weight. Bold is synthesised with Pillow's `stroke_width` because only
  a Regular CJK weight ships with the repo.
- Weather pictograms are drawn from primitives, not an icon font — chunky
  solid shapes survive repeated e-paper refreshes where fine glyphs ghost.
- Weekday names come from explicit Monday-first tables rather than
  `strftime("%a")`, so output does not vary with the Pi's locale.
- Added `WeatherInfo.precipitation_probability`. Open-Meteo publishes it
  only on the hourly series, so it is requested alongside `current` and
  matched to the current hour.

Branch: `refactor/ui_design`. Tests 68 -> 99.

### 2026-08-30 — Replace Calendar API with iCalendar feeds

**Discussion:**
Switched event fetching from the Google Calendar API to published `.ics`
feeds, so Apple iCloud and Google are read through one identical path.

**Decisions:**
- **Full replacement**, not a second source type. Deleted
  `infrastructure/google_calendar/` (service-account auth, repository,
  QR setup flow), `deploy/auth.sh`, and the `google-api-python-client` /
  `google-auth` dependencies. `service_account.json` is no longer used.
- Feed URLs are **bearer tokens** — anyone holding one can read the whole
  calendar. They live in `ics_feeds.toml`, which is gitignored, referenced
  by filename from the tracked `config.toml`. This mirrors the convention
  `service_account.json` already used. `ics_feeds.example.toml` documents
  the shape without the secrets.
- Logs identify a feed by name and host only, never by URL — these
  warnings land in the systemd journal. Two tests pin that.
- A feed ships recurring events as RRULE rules rather than expanded
  occurrences (the API expanded them server-side), so they are expanded
  client-side with `icalendar` + `recurring-ical-events`. Hand-rolling
  RRULE/EXDATE/RECURRENCE-ID was judged not worth the risk.
- Parsing is split from fetching (`events_from_ics`) so recurrence rules
  can be tested against fixture feeds with an injected `now`.
- A failing feed degrades to an empty list and logs a warning; one dead
  feed must never take the whole render down.

**Known follow-up:** `render/draw.py` still contains `render_setup` and
`render_setup_success`, which existed only for the deleted Google sharing
flow. They were deliberately left in place so this branch does not touch
`draw.py` and stays conflict-free with `refactor/ui_design`. Remove them
(and the `qrcode` dependency) once both branches are merged.

Branch: `refactor/ical-ics-source`. Tests 68 -> 94.

### 2026-08-30 — Onboarding server for feed URLs

**Discussion:**
The ICS switch inverted the direction of the secret. Under the API the
*device* held it (a service-account email) and a QR on the panel was a
perfect fit: display out, phone in. With feeds the *user* holds a 100+
character URL that must get *into* a box with no keyboard, camera or
touchscreen — and a display cannot accept input. SSH was the only path.

**Decisions:**
- On `--setup`, or whenever no feeds are configured, the Pi serves a form
  on the LAN and draws its own address, a QR of that address, and a
  6-digit PIN on the panel. The address is not a secret; the PIN is what
  stops another device on the same network writing feeds during the
  window (10 min default, closes on first success).
- `render_setup` / `render_setup_success` were repurposed rather than
  deleted — the QR-on-white-panel handling and dark layout carried over
  unchanged. This supersedes the earlier note to remove them.
- Submitted URLs are probed before saving, so a typo fails at the form
  instead of surfacing as a mysteriously empty calendar hours later.
- `--reset` deletes the saved feeds and reopens setup. It confirms first,
  and refuses outright when stdin is not a TTY unless `--yes` is given.
- The feeds file is written mode 600; it holds live credentials.

**Two bugs found while testing, both real:**
- `probe_feed` originally called `ICSRepository.fetch_events`, which
  swallows errors by design so one dead feed cannot take down a render.
  An unreachable URL therefore returned 0 events and *saved* — exactly
  the silent-empty-calendar failure the probe exists to prevent. A count
  of 0 cannot stand in for failure either, since a reachable calendar may
  legitimately have no upcoming events (the Apple one does). Split
  `fetch_raw()` out as the raising path and pointed the probe at it.
- `urllib3` logs the full request line at DEBUG, so a feed token reached
  the journal whenever debug logging was on. Our own logging was clean;
  the library was not. That logger is now held above DEBUG in
  `ics/repository.py`, with a test pinning it.

**Also fixed:** `deploy/setup.sh` never installed `spidev`/`gpiozero`,
which `vendor/waveshare_epd/epdconfig.py` imports — the venv is built
without `--system-site-packages`, so Pi OS's copies were invisible and
the first `--display` run failed with ImportError. `deploy/install.sh`
advertised `systemctl start` as the "manual run", but that unit ends in
`shutdown -h now` and powers the Pi off; corrected.

Branch: `feat/onboarding-server`, stacked on `refactor/ical-ics-source`.
Tests 94 -> 160.

## 2026-10-07

### 2026-10-07 — Wi-Fi setup over a hotspot

Moving to a Pi Zero WH, which may be handed a network it has never seen.
Instead of baking Wi-Fi into the SD image, the Pi now falls back to a
hotspot with a setup form when no saved network joins within 60 s.

- `infrastructure/wifi/nmcli.py` wraps NetworkManager. Commands are
  argument lists, never a shell, so a hostile SSID is just a name. Errors
  from calls carrying a password report nmcli's message, not the command.
- The Zero W has one radio: hotspot *or* client, and no scanning while the
  hotspot is up. The controller scans first, and rescans only during
  retry windows when the hotspot is down anyway.
- `wlan0` reports "connected" while serving the hotspot too, so
  `is_connected()` also checks the active connection is not our own AP.
- No PIN on this form, unlike the feed form: it is reachable only through
  a hotspot whose password is on the panel, which is already the proof of
  presence a PIN would provide.
- Submitting answers the phone first, then switches the radio; a failed
  join deletes the bad profile (otherwise retried every boot) and brings
  back the *same* hotspot, so the phone rejoins on its own.
- Every 5 min of form inactivity the hotspot drops to retry saved
  networks, so a router slower to boot than the Pi cannot strand it.
- `epd-wifi-setup.service` is a oneshot with `DefaultDependencies=no`: as
  a normal oneshot wanted by multi-user.target, boot would never finish
  while the hotspot waits. `Before=gcal-epd.service` keeps a timer-fired
  refresh from drawing over the setup screen.
- `--force` over SSH must be detached with `systemd-run`; the SSH session
  dies with the Wi-Fi and SIGHUP would take a foreground run with it.

Not verified on hardware yet: the nmcli calls are tested against a fake,
and the QR codes were checked by eye, not decoded.

Branch: `feat/wifi-ap-mode`. Tests 161 -> 216.

**2026-10-18 follow-up — pin the hotspot address.** `10.42.0.1` was an
assumption: `nmcli device wifi hotspot` lets NetworkManager pick the first
free `10.42.x.0/24`, so another shared connection (say a `usb0` gadget)
would move the hotspot to `10.42.1.1` while the panel QR still said
`10.42.0.1`. The hotspot is now built with `connection add` and
`ipv4.addresses 10.42.0.1/24`. Pinning alone is not enough — NetworkManager
accepts the same subnet on two interfaces and routing just breaks — so
`start_hotspot` first checks no other device holds `10.42.0.x` and fails
with a message naming it. Tests 216 -> 219.

**2026-10-18 follow-up — join the Wi-Fi and calendar flows.** Two gaps
between the setups, found walking the boot path end to end:
- A Pi that booted straight onto a known network (Wi-Fi from Imager) left
  `epd-wifi-setup` with nothing to do, and nothing else ran until the
  07:00/19:00 timer — a blank panel and no calendar setup QR for hours.
  The hand-over now fires on "online" as well as "joined".
- The hand-over started `gcal-epd.service`, which with no feeds opens the
  10-minute setup form — under `TimeoutStartSec=120`. systemd killed the
  form at two minutes. The form now has its own `epd-feed-setup.service`
  (900 s), and the two units carry opposite `ConditionPathExists` on
  `ics_feeds.toml`, so systemd picks the right one with no code knowing
  about the other. `gcal-epd.service` passes the new `--no-setup`, so the
  scheduled refresh never waits on a person even if the file is empty.
Tests 219 -> 225.

**2026-10-18 follow-up — slow Wi-Fi form, found on hardware.** The form
loaded slowly from a phone. Two causes, both in the serving model:
- It was a single-threaded `HTTPServer` with no socket timeout. Browsers
  open speculative connections they may never send on; the server sat in
  that idle socket while the real request waited. Reproduced locally: one
  idle connection held the page for over 8 s.
- `handle_request()` ran only from the controller loop, which blocks for
  ~40 s on every panel refresh — e.g. reloading the page right after a
  wrong password, while the panel is drawing the error.
The form now runs as a `ThreadingHTTPServer` on its own thread with a
10 s per-connection timeout; the controller only waits on an Event for a
submission. Tests 225 -> 228.

**2026-10-18 follow-up — units become templates.** `/home/admin/google-calendar-api`
was hardcoded once in `gcal-epd.service` on `develop`; this branch had spread
it to 10 places across three units, two of them `ConditionPathExists` lines
that pick which unit runs — so a wrong path would not fail, it would just
silently skip the unit. The units now carry `@PROJECT_DIR@`, `@USER@` and
`@FEEDS_FILE@`; `install.sh` fills them from the checkout's own location, its
owner, and `config.toml`'s `feeds_file` (asked of the app itself via
`_feeds_path`, so the two cannot disagree), refuses a path systemd cannot
take, and refuses to install a unit with a placeholder left unfilled.
`%h` was no help: in a system unit it is root's home. A test pins that no
unit names `/home/` and that every placeholder is one install.sh fills.
Tests 228 -> 238.

## 2026-10-18

### 2026-10-18 — Shared config module

Checking the architecture diagrams against the code turned up two smells.
`wifi_setup` imported `main` — one entry point depending on another — only
to call `load_config()` and read `_PROJECT_ROOT`; that also dragged the
calendar, weather and onboarding modules (and `requests`, `icalendar`)
into the root-run Wi-Fi setup. And "resolve `display.font_path` against the
checkout" was written out three times: `main._push_screen`,
`display_service.run` and `wifi_setup._make_push`.

`gcal_epd/config.py` now owns `PROJECT_ROOT`, `load_config`, `resolve`,
`font_path` and `feeds_file`. Both entry points, the application layer and
`install.sh` read settings from it. A test runs the Wi-Fi panel path in a
fresh interpreter and asserts `gcal_epd.main` was never imported; it fails
against the old code. Behaviour is unchanged. Tests 238 -> 246.

### 2026-10-18 — main.py back to a composition root

Reviewing where `main.py` sits in the architecture: of its jobs, four belong
to an entry point (parse args, build the repositories, pick setup vs refresh,
the interactive `--reset` prompt) and two did not.

- **The feeds file had two owners.** `onboarding/server.py` wrote it
  (`render_feeds_toml`, `write_feeds_file`, `reset_feeds`) while `main.py`
  read it (`load_feeds`). All four now live in
  `infrastructure/feeds_file.py`, with a round-trip test: the module must
  read back exactly what it writes.
- **The setup flow lived in the entry point.** The refresh had an
  application service (`display_service`) but setup was inline in `main.py`.
  `run_onboarding` and the panel push moved to
  `application/setup_service.py`. `feat/one-step-setup` will grow this
  flow, so it now has a home that is not the entry point.
- **Both entry points called `logging.basicConfig` at import**, so
  importing either (tests, tools, and formerly `wifi_setup` importing
  `main`) reconfigured the importer's logging. Moved into each `main()`;
  a test checks importing both leaves the root logger without handlers,
  and fails against the old code.

Left as is: `_build_event_repos` reads every ics source's `feeds_file`,
while setup and reset use only the first. Harmless with the one source in
`config.toml`. No behaviour change. Tests 246 -> 253.

### 2026-10-18 — Docs rewritten, in English and Traditional Chinese

The README had drifted far from the code: it still described Google Calendar
on a 64-bit Pi 4, listed none of the Wi-Fi, onboarding, config or feeds-file
modules, numbered deployment steps 1 then 5, said the timer ran hourly, and
told readers to `cp` unit files that are now templates. It is rewritten
around the actual first-boot flow (flash → `setup.sh` → `install.sh` →
reboot, then the panel guides Wi-Fi and calendar setup).

The architecture diagrams, checked line by line against the code earlier
today, moved into `docs/ARCHITECTURE.md` and were updated for the shared
`config.py`, `setup_service.py` and `feeds_file.py`. The personal boot
timeline (LAN IP, hotspot name) stays out of the repo.

Both files have a `.zh-TW.md` twin; English is the source. A test compares
the skeleton of each pair — heading outline, tables, and every Mermaid
diagram with its quoted text stripped — so a translated label passes but a
section or an arrow added to one language only fails. Checked by mutation:
an extra arrow and an extra heading in the Chinese file each fail it.
`README.MD` was renamed `README.md` to pair with `README.zh-TW.md`.
Tests 253 -> 261.

### 2026-10-18 — One-step setup: calendar links on the hotspot form

Hardware testing of the Wi-Fi flow showed the second QR scan as the weak
point: after the hotspot closes the phone must find its way back to the
home network before the calendar form is reachable. A WebSocket or a
redirect cannot bridge that — the hotspot address is gone and the Pi's
LAN address is not known in advance — so the links are collected up front.

- The hotspot form gains an optional "Calendar links" box. Only the form
  is validated there; the hotspot has no internet to fetch a feed.
- After a successful join the Wi-Fi setup (root) parks them with
  `feeds_file.write_pending_feeds` in `ics_feeds.pending.toml`, same
  format, mode 600, chowned to the checkout's owner.
- `epd-feed-setup.service` now also runs when that file exists (systemd
  `|` OR-conditions on `@FEEDS_FILE@` / `@PENDING_FILE@`, both filled by
  `install.sh` from the app), and `gcal-epd.service` stands down while it
  does. `main` calls `setup_service.apply_pending_feeds` first. All good:
  they become `ics_feeds.toml` and the calendar renders with no further scan.
- Any failure reopens calendar setup with the reason on the panel (red)
  and the form. `onboarding.inspect_feed` tells apart unreachable, an HTTP
  status, and "not a calendar (iCal) file", naming only the host. The
  pending file is removed either way, so a bad link is not retried every
  boot, and working feeds from before are not replaced.

Written before #13/#14 and rebuilt on top of them: the pending helpers sit
in `feeds_file.py` (format owner) and the check-and-apply step in
`setup_service.py` (setup flow); nothing imports `main`.

Follow-ups found on hardware, each its own commit on this branch: the
first-run "feed file not found" is logged at INFO, not ERROR; the refresh
log states the measured 15–30 s instead of ~36 s; calendar setup no longer
draws "Connected!" right before the calendar (one refresh fewer);
`epd-feed-setup` is `Before=gcal-epd.service`, so a timer run waits for
setup instead of racing it for the panel; and `install.sh` no longer warns
that `systemctl start` powers the Pi off. README and architecture, in both
languages, describe the one-step flow. Tests 261 -> 283.

### 2026-10-18 — Offline first-boot install on an Imager-flashed card

Goal: put `develop` on an SD card already flashed with Raspberry Pi Imager
(Pi OS Lite 2026-10-06, Trixie armhf, Python 3.13; user `admin`, SSH key, no
Wi-Fi) so it sets itself up at power-on with no network.

What the card needed that the image lacks:
- Pillow's piwheels wheel links against 12 libraries Lite does not ship
  (freetype, openjp2, lcms2, webp demux/mux, avif and its AV1 codecs, yuv),
  plus `watchdog` for install.sh. Resolved with `apt-get install
  --download-only` inside the real image rootfs, imported into Docker and run
  under ARM emulation, so the dependency closure matches the card exactly.
- Python wheels for `linux_armv6l` / cp313 from piwheels, all prebuilt.
  `python3-venv`, NetworkManager and `dnsmasq-base` are already in Lite.

Bundle on the boot partition (`epd-bundle/`): `app.tar` (git archive of
develop), `debs/`, `wheels/`, `firstboot.sh`. `user-data` runcmd runs
`firstboot.sh` (dpkg -i, venv, offline pip, `deploy/install.sh`), then
`power_state` reboots when `/var/lib/epd-firstboot.done` exists.
`dtparam=spi=on` set in `config.txt` directly. Dry-run in the emulated rootfs
with `--network none` passed (venv, imports, CJK text render, idempotent rerun).

Pitfalls hit, in order:
1. **cloud-init runs once per instance.** The card had been booted before the
   bundle was added, so the instance (`rpi-imager-…`) had already run its
   runcmd with the original 731-byte `user-data`; later boots reuse the cache
   and skip it. Fix: new instance id in both `meta-data` and the `ds=nocloud;i=`
   of `cmdline.txt`.
2. **uid 1000 is `pi` in the stock rootfs**, not the Imager user — the user
   is passed explicitly (`EPD_USER=admin`).
3. **QEMU reports armv7l** by default, so pip in the emulator rejects
   armv6l wheels; armv7l copies were bundled for the dry run.
4. **macOS writes `._*` AppleDouble files** onto FAT; removed after copying.
5. **Docker Desktop holds the card** after a `-v` mount of it; quit Docker
   to eject.
6. **Logs on ext4 are unreadable from macOS** without root: `debugfs` from
   Homebrew `e2fsprogs`, run with sudo in Terminal (the `!` prompt has no TTY
   for sudo). `firstboot.sh` now tees its log to `/boot/firmware` too.

Result: install completed in ~5 min (08:31:47 → 08:36:59 Pi clock) and the
Pi rebooted, but no hotspot and nothing on the panel. The journal is volatile
on Pi OS (empty `/var/log/journal`), so `epd-diag.timer` (4 min after boot,
every 3 min) was added to copy rfkill, nmcli, iw, journals and kernel Wi-Fi
lines to `/boot/firmware/epd-diag.log`, readable from a Mac without sudo.

**Root cause: the Wi-Fi radio is off at two levels on a card with no Wi-Fi
configured.** Pi OS leaves Wi-Fi rfkill-blocked, and NetworkManager's state
file has `WirelessEnabled=false`, until a country is set through Imager or
raspi-config. NetworkManager logged "Wi-Fi disabled by radio killswitch;
disabled by state file" at start; `nmcli connection up epd-setup-ap` failed
with "No suitable device found"; `start_hotspot` deleted the connection and
raised, and the service exited 1 with nothing on the panel. The cloud-init
`rfkill unblock wifi` ran ~2 min too late, and alone would not have been
enough. Development Pis never hit this: their Wi-Fi was set up in Imager.

Fix on the card: a drop-in on `epd-wifi-setup.service` with
`ExecStartPre=-rfkill unblock wifi` and `ExecStartPre=-nmcli radio wifi on`.
The same drop-in went into the image build. Follow-ups: the app could turn
the radio on itself before the hotspot, and a hotspot failure should show on
the panel instead of exiting silently.

## 2026-10-19

### 2026-10-19 — Ready-to-flash image and tag-driven release (PR #17)

Installing on the Pi is slow (a Pi Zero spends minutes in dpkg and pip) and
fragile (cloud-init once-per-instance). Building the image ahead of time
removes both: the Pi installs nothing.

- `image/build.sh` grows the pinned base image (`image/base.env`) by 768MB,
  chroots in under ARM emulation, installs the Pillow libraries and
  `watchdog`, builds `.venv` in `/opt/e-pages` owned by system user `epd`,
  runs `deploy/install.sh` unchanged with `sudo`/`systemctl start|status`
  stubbed, sets SPI, Wi-Fi country and an `rfkill unblock wifi` drop-in, then
  zerofree + xz.
- `QEMU_CPU=arm1176` makes the chroot report armv6l, so pip picks Pi Zero
  wheels; the build fails if it does not. piwheels' armv6l wheels carry
  `armv7l` in their `WHEEL` metadata; the binaries are ARMv6
  (`Tag_CPU_arch: v6`), so that tag is not a problem.
- Docker Desktop's kernel cannot mount vfat: the boot partition's
  `config.txt`/`cmdline.txt` are copied out and back with mtools, and the
  build fails if anything else was written there.
- `.github/workflows/release-image.yml`: tests, then build, then
  `gh release create` on a `v*` tag; manual runs keep an artifact. Pushing it
  needed `gh auth refresh -s workflow`.
- `deploy/` untouched so the branch cannot conflict with feat/one-step-setup.

First local build: `e-pages-af02b93.img.xz`, 579MB. Inspected: units on
`/opt/e-pages` as `epd`, timer/wifi-setup/watchdog enabled, build stubs and
apt lists removed. Not yet booted on hardware; the open hotspot issue above
may apply to it too.

### 2026-10-19 — Radio on before each use of it (PR #18, fix/wifi-radio-on)

The app-level fix for the root cause above, so the hotspot does not depend
on a systemd drop-in. `NetworkManager.radio_on()` runs `rfkill unblock wifi`
and `nmcli radio wifi on`, then waits up to 15 s for `wlan0` to leave
`unavailable` (nmcli state < 30). It runs before every use of the radio —
`wait_connected`, `scan`, `start_hotspot`, `resume_hotspot`, `connect` —
because on the test card NetworkManager logged "Wi-Fi now disabled by radio
killswitch" ~20 s after it started, one second before `epd-wifi-setup`
began: something in Pi OS blocks Wi-Fi again partway through boot (not yet
identified). Failures are logged, not raised. Only `nmcli.py` and its tests
change, so the branch cannot conflict with #16. Tests 261 → 270; dropping
the call from `start_hotspot` or skipping the wait fails 3 of the new ones.

Field notes from the card, same day:
- **What re-blocks Wi-Fi during boot is `systemd-rfkill.service`**, restoring
  the saved state `/var/lib/systemd/rfkill/platform-20300000.mmcnr:wlan:1`.
  Once an unblock is saved, later boots stay unblocked; until then every boot
  starts blocked — another reason to unblock right before each use.
- **Pulling the power loses recent writes.** The round that installed the
  radio drop-in through cloud-init was unplugged seconds after cloud-final
  ran: cloud-init's once-per-instance markers survived, the copied drop-in
  did not, so the next boot skipped it. Anything written for a test must be
  followed by `sync`.
- The diagnostics timer, which runs a script from the boot partition every
  boot, became the reliable way to change the card: it now installs PR #18's
  `nmcli.py` into the app, syncs, and restarts `epd-wifi-setup`.

### 2026-10-19 — Hotspot with PMF off (PR #19, fix/hotspot-pmf)

With the radio on (PR #18), the hotspot failed one step later: "802.1X
supplicant took too long to authenticate" after 25 s, preceded by
"nl80211: kernel reports: key setting validation failed". Six variants of
the app's hotspot were run on the Pi from a boot-partition script (Trixie,
wpa_supplicant 2.10-24+rpt3, NetworkManager 1.52.1, kernel 6.18.50):

| Variant | Result |
|---|---|
| App's settings | failed after 26 s |
| PMF off | up in 8 s, seen on a phone |
| Channel 6 | failed after 26 s |
| PMF off + channel 6 | up in 7 s |
| NetworkManager's security defaults | failed after 26 s |
| Open | up in 7 s |

The brcmfmac driver rejects the PMF management-frame key in AP mode; the
channel does not matter. `start_hotspot` adds `wifi-sec.pmf disable` and
keeps WPA2-AES. Likely a Trixie regression — the hotspot worked on hardware
before, probably on Bookworm. #18 and #19 edit different parts of
`nmcli.py` and merge cleanly (271 tests together). The first run of the
experiment script failed on my argument order (`ssid` before `type wifi`);
the second was checked against the image's real nmcli (`--offline`) first.

### 2026-10-19 — Blank panel: gpiozero without lgpio

With the hotspot up the panel stayed blank. `epd-wifi-setup` logged an
`EINVAL` from gpiozero: `.venv` had no `lgpio`, so gpiozero fell back to its
`NativeFactory`, which fails on kernel 6.18. The venv does not see system
site-packages, so Pi OS's own `python3-lgpio` does not help; only
`liblgpio1` (already in Lite) is needed under the piwheels wheel
`lgpio-0.2.2.0-cp313-cp313-linux_armv6l.whl`.

Installed on the card by the diagnostics script (`pip install --no-index`,
as `admin`), then Wi-Fi setup restarted: the QR appeared. **Not fixed in the
repo yet:** `deploy/setup.sh` installs only `spidev` and `gpiozero`, and the
image build does the same, so a fresh install still gets a blank panel.

### 2026-10-19 — iPhone could not join the hotspot: WPA-PSK only (PR #20)

With the radio on (#18), PMF off (#19) and the QR on the panel, an iPhone
still could not join: "Unable to join the network" from the QR, "Incorrect
password" when typed. The diagnostics script turned wpa_supplicant's log up
to debug over D-Bus (`busctl set-property … DebugLevel s debug`, keys
hidden) and the next attempts showed:

- Association, then message 1/4 and 2/4 of the handshake. **Message 2/4's
  MIC verified**, so the password matched.
- 0.01 s after message 3/4 was sent, the driver deleted the station
  (`NL80211_CMD_DEL_STATION`, reason 0). Too fast for a timeout: one side
  gave up on purpose.
- NetworkManager's hotspot offered two AKMs, PSK and PSK-SHA256
  (`key_mgmt_suites=0x102`; the beacon's RSN element lists `00-0f-ac:2` and
  `:6`), although `wifi-sec.pmf` was `disable`. NetworkManager 1.52 has no
  setting to drop the second.
- The Zero W's brcmfmac runs the AP's SME in firmware (`device_ap_sme=1`),
  so the beacon on air is the firmware's.

Most likely the security element the firmware broadcasts does not match the
one in message 3/4; a client must then abort (downgrade protection), and
iOS reports that as a wrong password. That part is inferred, not captured
on air. What settled it was an experiment from the boot partition
(`ap-test2.sh`): NetworkManager let go of `wlan0`, and a separate
wpa_supplicant ran a WPA2 AP with `key_mgmt=WPA-PSK` only. The iPhone joined
at once and stayed `authorized: yes`.

The fix makes the hotspot a strategy (`infrastructure/wifi/hotspot.py`),
picked with `--hotspot`:

- `wpa-supplicant` (default, `wpa_hotspot.py`): own wpa_supplicant (WPA2,
  CCMP, WPA-PSK only, PMF off) plus dnsmasq for DHCP at the same pinned
  `10.42.0.1`. While it runs, `wlan0` is `managed no` and the system
  wpa_supplicant is stopped; both get it back when the hotspot goes down,
  and it waits until NetworkManager can use `wlan0` again. Scanning and
  joining the home network stay with NetworkManager.
- `networkmanager`: the hotspot as before, kept for comparison.

`WifiWithHotspot` has the methods `wifi_setup.run` already calls, so `run()`
is unchanged; only `main()` builds it. The password reaches wpa_supplicant
only as its derived PSK (PBKDF2, checked against the IEEE 802.11i test
vector), in a 0600 file under `/run/epd-hotspot`, never on a command line.
SIGTERM now ends Wi-Fi setup like Ctrl-C, so `systemctl stop` also hands
`wlan0` back.

Tested on the Zero W through the diagnostics script, which swapped the new
files into the installed app: the iPhone joined, the form at `10.42.0.1`
worked, the Pi joined the home network, calendar setup finished and events
were drawn. After a reboot it went straight online. Pi 4 not tested yet.
Tests 262 → 293.

A conflict with #16 slipped through: an early `git merge-tree` check passed
before the SIGTERM handler was added, and the handler then landed where #16
adds `_stash_feeds`. Found by merging all open PRs onto `develop` in order
and running the tests; the handler moved, no behaviour change.

### 2026-10-19 — State at the end of the Pi Zero work

Merged into `develop`: #16 (one-step setup), #18 (radio on), #19 (PMF off),
#20 (WPA-PSK-only hotspot). With all of them, 326 tests pass. #17 (image
release) is a draft and on hold. Before it is reviewed it needs a rebuild on
the new `develop`, lgpio, and a boot on hardware.

Open follow-ups:
- **lgpio** in `deploy/setup.sh` and the image build (above).
- **Wait for time sync before rendering.** The Pi has no RTC; until
  timesyncd syncs, the clock resumes from
  `/var/lib/systemd/timesync/clock` (it read 6 Oct on the 19th). The
  calendar starts as soon as there is a network and could draw the wrong
  day. Not seen yet; `systemd-time-wait-sync` plus `After=time-sync.target`
  would close it.
- **Recover `wlan0` at start-up** if Wi-Fi setup died hard (SIGKILL, crash)
  while our hotspot held it.
- **Skip `BOOT_WAIT`** when there are no saved Wi-Fi profiles: a fresh card
  waits 60 s for nothing.
- **Show a hotspot failure on the panel** instead of exiting silently.
- **Captive portal:** answer DNS with `10.42.0.1` so the phone opens the
  form by itself.
- Test #20 on a Pi 4 and a Zero 2 W.

Debugging this card taught a few things worth keeping. The journal is
volatile, so a timer copied diagnostics to the FAT boot partition, readable
from a Mac without sudo. Changes reached the Pi through that same script,
not by hand. Every write was followed by `sync`, because the power is
pulled at any moment. Docker must never bind-mount a file from the card,
or it holds the card until Docker quits.
