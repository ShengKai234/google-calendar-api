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
