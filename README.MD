# Google Calendar e-Paper Display

Fetches Google Calendar events and renders them on a Waveshare 7.3" 7-color e-Paper display via Raspberry Pi.

---

## Hardware

| Component | Spec |
|-----------|------|
| Raspberry Pi | Pi 4 Model B Rev 1.5 — 8GB |
| Storage | MicroSD 64GB |
| Display | [Waveshare 7.3inch e-Paper HAT (F)](https://www.waveshare.net/shop/7.3inch-e-Paper-HAT-F.htm) — 800×480, 7-color |
| OS | Raspberry Pi OS Lite (64-bit) |

---

## Project Structure

```
google-calendar-api/
├── src/gcal_epd/
│   ├── domain/              # CalendarEvent / WeatherInfo + repository Protocols
│   ├── infrastructure/
│   │   ├── ics/             # iCalendar feed repository
│   │   └── open_meteo/      # Weather repository
│   ├── application/         # Orchestrates fetch -> render -> display
│   ├── render/
│   │   ├── layout.py        # Layout calculation (geometry, grouping)
│   │   └── draw.py          # Pillow drawing logic
│   ├── epd.py               # e-Paper display push
│   └── main.py              # Entry point
├── vendor/waveshare_epd/    # Waveshare driver (epd7in3f + epdconfig)
├── assets/fonts/            # NotoSansCJKtc-Regular.otf
├── deploy/                  # systemd service / timer / install script
├── config.toml              # Runtime configuration (tracked)
├── ics_feeds.toml           # Your feed URLs (gitignored — secret!)
├── ics_feeds.example.toml   # Template for the above
├── pyproject.toml           # Package definition
└── test_display.py          # Standalone display hardware test
```

---

## Prerequisites

- Python 3.11+
- One or more calendar feed URLs in iCalendar (`.ics`) format

No Google Cloud project, API key or OAuth consent screen is required — the
app reads published `.ics` feeds over plain HTTPS.

---

## First-Time Setup

### 1. Clone the repo

```bash
git clone <repo-url> google-calendar-api
cd google-calendar-api
```

### 2. Run setup script

```bash
bash deploy/setup.sh
```

This script will:
- Install system dependencies (`python3-venv`, `python3-dev`)
- Enable SPI automatically
- Create `.venv` and install all Python packages
- Check for `ics_feeds.toml` and guide you if missing

### 3. Add your calendar feeds

```bash
cp ics_feeds.example.toml ics_feeds.toml
```

Edit `ics_feeds.toml` and paste in your feed URLs:

```toml
[[feed]]
name = "Apple"                       # optional; defaults to the feed's own name
url  = "webcal://p1-caldav.icloud.com/published/2/..."

[[feed]]
name = "Google"
url  = "https://calendar.google.com/calendar/ical/.../basic.ics"
```

> **Treat these URLs like passwords.** Anyone who has one can read that
> calendar. `ics_feeds.toml` is gitignored for exactly this reason — never
> commit it. To revoke a leaked URL, re-publish (Apple) or reset the private
> address (Google); the old link stops working.

**Where to find the URL**

| Source | Path |
|--------|------|
| Apple Calendar | Calendar app → right-click calendar → Share Calendar → tick **Public Calendar** → Copy Link (`webcal://…`) |
| Google Calendar | Settings → pick a calendar → Integrate calendar → **Secret address in iCal format** |

Any other CalDAV/iCalendar publisher works too — Outlook, Fastmail, a
university timetable — as long as it serves an `.ics` URL.

### 4. Render a preview

```bash
. .venv/bin/activate
python -m gcal_epd.main
```

Writes `preview.png`. No hardware needed.

### 5. Test the display

```bash
python test_display.py
```

### 6. Full run

```bash
python -m gcal_epd.main --display
```

---

## Configuration

Runtime behaviour lives in `config.toml` (tracked). Secrets live in
`ics_feeds.toml` (gitignored) — see step 3 above.

```toml
[[sources]]
type = "ics"
feeds_file = "ics_feeds.toml"         # where your feed URLs live
days_ahead = 14                       # how far ahead to look
max_results_per_calendar = 100

[[sources]]
type = "open_meteo"                   # weather widget; no API key needed
latitude = 25.0330
longitude = 121.5654
location = "Taipei"

[display]
output_path = "preview.png"           # rendered image output path
font_path = "assets/fonts/NotoSansCJKtc-Regular.otf"
```

Add as many `[[feed]]` blocks to `ics_feeds.toml` as you like — they are
merged into one chronological list.

---

## Running

### Preview only (no hardware needed)

```bash
source .venv/bin/activate
python -m gcal_epd.main
```

Renders calendar to `preview.png`.

### Display hardware test

```bash
python test_display.py
# → pushes color swatches + grid to e-Paper display
```

### Full run with e-Paper push

```bash
source .venv/bin/activate
python -m gcal_epd.main --display
```

---

## Raspberry Pi Deployment

> Complete First-Time Setup above before running these steps.

### 1. Install systemd timer and watchdog

```bash
bash deploy/install.sh
```

This script will:
- Copy `gcal-epd.service` and `gcal-epd.timer` to `/etc/systemd/system/`
- Enable and start the timer (runs hourly by default)
- Enable the hardware watchdog (auto-reboot on system hang)
- Prompt to reboot (required for watchdog)

### 5. Verify

```bash
# Check timer status and next run time
systemctl status gcal-epd.timer

# View logs
journalctl -u gcal-epd.service -n 50

# Trigger a manual run
sudo systemctl start gcal-epd.service
```

---

## Schedule

Default: **07:00 and 19:00 (Taiwan time)**.  
To change, edit `deploy/gcal-epd.timer`:

```ini
# 07:00 and 19:00 (default)
OnCalendar=*-*-* 07:00:00
OnCalendar=*-*-* 19:00:00

# Every hour
OnCalendar=hourly

# Every day at 07:00 only
OnCalendar=*-*-* 07:00:00
```

> Make sure the Raspberry Pi timezone is set to `Asia/Taipei`:
> ```bash
> sudo timedatectl set-timezone Asia/Taipei
> ```

After editing, redeploy:

```bash
sudo cp deploy/gcal-epd.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart gcal-epd.timer
```

---

## Maintenance

### Update dependencies

```bash
source .venv/bin/activate
pip install -r requirements-to-freeze.txt --upgrade
pip freeze > requirements.txt
```

### Rotate a calendar feed URL

If a feed URL leaks, revoke it at the source — the old link stops working
immediately:

- **Apple**: Calendar → right-click calendar → Share Calendar → untick and
  re-tick **Public Calendar** to mint a new link.
- **Google**: Settings → calendar → Integrate calendar → **Reset private URLs**.

Then paste the new URL into `ics_feeds.toml`.
