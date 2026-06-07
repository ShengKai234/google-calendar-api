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
│   ├── render/
│   │   ├── layout.py        # Layout calculation (geometry, grouping)
│   │   └── draw.py          # Pillow drawing logic
│   ├── auth.py              # Google OAuth token management
│   ├── calendar_client.py   # Google Calendar API
│   ├── epd.py               # e-Paper display push
│   └── main.py              # Entry point
├── vendor/waveshare_epd/    # Waveshare driver (epd7in3f + epdconfig)
├── assets/fonts/            # NotoSansCJKtc-Regular.otf
├── deploy/                  # systemd service / timer / install script
├── config.toml              # Runtime configuration
├── pyproject.toml           # Package definition
└── test_display.py          # Standalone display hardware test
```

---

## Prerequisites

- Python 3.11+
- Google Cloud project with Calendar API enabled
- `credentials.json` from Google Cloud Console (OAuth 2.0 Desktop app)

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
- Check for `credentials.json` and `token.json` and guide you if missing

### 3. Place credentials

Copy `credentials.json` (from Google Cloud Console) to the project root:

```
google-calendar-api/
└── credentials.json   ← here
```

### 4. Google Calendar authentication

Raspberry Pi OS Lite is headless (no browser). Generate `token.json` on any machine that has a browser:

```bash
# On a machine with a browser (Mac / PC)
source .venv/bin/activate
python -m gcal_epd.main
# → browser opens → sign in → token.json is created
```

Then copy `token.json` to the Pi:

```bash
scp token.json admin@<pi-ip>:~/google-calendar-api/
```

Subsequent runs on the Pi will refresh the token automatically without a browser.

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

Edit `config.toml` to adjust behavior:

```toml
[auth]
credentials_file = "credentials.json"
token_file = "token.json"

[calendar]
days_ahead = 7                        # How many days ahead to fetch
max_results_per_calendar = 100
include_access_roles = ["owner"]      # "owner" | "writer" | "reader"

[display]
output_path = "preview.png"           # Rendered image output path
font_path = "assets/fonts/NotoSansCJKtc-Regular.otf"
```

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

Default: **every hour**.  
To change, edit `deploy/gcal-epd.timer`:

```ini
# Every hour (default)
OnCalendar=hourly

# Every day at 07:00
OnCalendar=*-*-* 07:00:00

# Every day at 07:00 and 19:00
OnCalendar=*-*-* 07,19:00:00
```

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

### Re-authenticate Google Calendar

Delete `token.json` and run again — a browser window will open:

```bash
rm token.json
python -m gcal_epd.main
```
