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
echo "[1/5] Installing system dependencies..."
sudo apt-get update -q
sudo apt-get install -y python3-venv python3-dev
echo "      Done."

# --- SPI ---
echo "[2/5] Checking SPI..."
if ls /dev/spidev* &>/dev/null; then
    echo "      SPI already enabled."
else
    echo "      SPI not detected. Enabling via raspi-config..."
    sudo raspi-config nonint do_spi 0
    echo "      SPI enabled."
fi

# --- Virtual environment ---
echo "[3/5] Setting up Python virtual environment (.venv)..."
cd "$PROJECT_DIR"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "      Created .venv"
else
    echo "      .venv already exists, skipping."
fi

# --- Python packages ---
echo "[4/5] Installing Python packages..."
. "$PROJECT_DIR/.venv/bin/activate"
pip install --quiet -e .
pip install --quiet -r "$PROJECT_DIR/requirements.txt"
echo "      Done."

# --- Check credentials ---
echo "[5/5] Checking credentials..."
if [ -f "$PROJECT_DIR/service_account.json" ]; then
    echo "      service_account.json found."
else
    echo ""
    echo "  [!] service_account.json not found."
    echo "      Copy it from your laptop:"
    echo "        scp service_account.json admin@<pi-ip>:$PROJECT_DIR/"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Copy service_account.json to this Pi (if not done):"
echo "       scp service_account.json admin@<pi-ip>:$PROJECT_DIR/"
echo "  2. Run calendar sharing setup (draws QR on e-paper):"
echo "       bash deploy/auth.sh --display"
echo "  3. Install systemd timer for automatic refresh:"
echo "       bash deploy/install.sh"
