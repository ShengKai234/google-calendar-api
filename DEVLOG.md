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
