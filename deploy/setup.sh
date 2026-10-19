#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== gcal-epd setup ==="
echo "Project: $PROJECT_DIR"
echo ""

# --- Verify running on Raspberry Pi ---
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo "Warning: This script is intended for Raspberry Pi."
    read -rp "Continue anyway? [y/N] " confirm
    case "$confirm" in [Yy]) ;; *) exit 1 ;; esac
fi

# --- System packages ---
echo "[1/6] Installing system dependencies..."
sudo apt-get update -q
sudo apt-get install -y python3-venv python3-dev
echo "      Done."

# --- SPI ---
echo "[2/6] Checking SPI..."
if ls /dev/spidev* &>/dev/null; then
    echo "      SPI already enabled."
else
    echo "      SPI not detected. Enabling via raspi-config..."
    sudo raspi-config nonint do_spi 0
    echo "      SPI enabled."
fi

# --- Virtual environment ---
echo "[3/6] Setting up Python virtual environment (.venv)..."
cd "$PROJECT_DIR"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "      Created .venv"
else
    echo "      .venv already exists, skipping."
fi

# --- Python packages ---
echo "[4/6] Installing Python packages..."
. "$PROJECT_DIR/.venv/bin/activate"
pip install --quiet -e .
pip install --quiet -r "$PROJECT_DIR/requirements.txt"
# The Waveshare driver imports these; they are not in requirements.txt
# because they only exist on the Pi. The venv is built without
# --system-site-packages, so Pi OS's copies are not visible to it.
if grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    pip install --quiet spidev gpiozero
    echo "      Installed spidev + gpiozero (e-Paper driver)."
fi
echo "      Done."

# --- Check calendar feeds ---
echo "[5/6] Checking calendar feeds..."
if [ -f "$PROJECT_DIR/ics_feeds.toml" ]; then
    echo "      ics_feeds.toml found."
else
    echo ""
    echo "  [!] ics_feeds.toml not found."
    echo "      Copy the template and add your feed URLs:"
    echo "        cp ics_feeds.example.toml ics_feeds.toml"
    echo "      Or copy your existing one from your laptop:"
    echo "        scp ics_feeds.toml admin@<pi-ip>:$PROJECT_DIR/"
fi

# --- PiSugar 3 battery (optional) ---
# With a PiSugar 3 the Pi is off between refreshes and its RTC alarm wakes
# it (gcal_epd.power_manager). That needs PiSugar's own daemon,
# pisugar-server, from PiSugar's official installer (docs.pisugar.com,
# github.com/PiSugar/pisugar-power-manager-rs). Without a PiSugar, skip it:
# the display then simply stays on.
echo "[6/6] PiSugar battery (optional)..."
if dpkg -s pisugar-server &>/dev/null; then
    echo "      pisugar-server already installed."
elif ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null || [ ! -t 0 ]; then
    echo "      Skipped (not a Raspberry Pi, or no terminal to ask)."
else
    echo "      Only for a Pi powered by a PiSugar 3 battery board."
    read -rp "      Is this Pi on a PiSugar 3, and install pisugar-server? [y/N] " pisugar
    case "$pisugar" in
        [Yy])
            PISUGAR_TMP="$(mktemp -d)"
            # Downloaded, then run: not piped into a shell. A failure here
            # must not undo the rest of the setup, so no `set -e` exit.
            if wget -q -O "$PISUGAR_TMP/pisugar-power-manager.sh" \
                    https://cdn.pisugar.com/release/pisugar-power-manager.sh; then
                echo "      PiSugar's installer asks for the model: choose \"PiSugar 3\"."
                echo "      Leave its \"auto power on\" off: it disables the wake-up alarm."
                if bash "$PISUGAR_TMP/pisugar-power-manager.sh" -c release; then
                    echo "      Installed pisugar-server and pisugar-poweroff."
                else
                    echo "      [!] PiSugar's installer failed; the display stays always on."
                fi
            else
                echo "      [!] Could not download PiSugar's installer; skipped."
            fi
            rm -rf "$PISUGAR_TMP" ;;
        *)
            echo "      Skipped. Run deploy/setup.sh again to install it later." ;;
    esac
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Add your calendar feeds — either scan the QR on the panel:"
echo "       .venv/bin/python -m gcal_epd.main --setup --display"
echo "     or edit the file directly:"
echo "       cp ics_feeds.example.toml ics_feeds.toml && nano ics_feeds.toml"
echo "  2. Render once to check it works:"
echo "       .venv/bin/python -m gcal_epd.main"
echo "  3. Install systemd timer for automatic refresh:"
echo "       bash deploy/install.sh"
