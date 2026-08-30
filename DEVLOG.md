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
