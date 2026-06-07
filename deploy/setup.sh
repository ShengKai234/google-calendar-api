#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== gcal-epd setup ==="
echo "Project: $PROJECT_DIR"
echo ""

# --- 確認在 Raspberry Pi 上執行 ---
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo "Warning: This script is intended for Raspberry Pi."
    read -rp "Continue anyway? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || exit 1
fi

# --- 系統套件 ---
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

# --- 虛擬環境 ---
echo "[3/5] Setting up Python virtual environment (.venv)..."
cd "$PROJECT_DIR"
if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
    echo "      Created .venv"
else
    echo "      .venv already exists, skipping."
fi

# --- Python 套件 ---
echo "[4/5] Installing Python packages..."
source "$PROJECT_DIR/.venv/bin/activate"
pip install --quiet -e .
pip install --quiet RPi.GPIO spidev gpiozero lgpio
echo "      Done."

# --- 確認 credentials.json ---
echo "[5/5] Checking credentials..."
if [[ -f "$PROJECT_DIR/credentials.json" ]]; then
    echo "      credentials.json found."
else
    echo ""
    echo "  [!] credentials.json not found."
    echo "      Download it from Google Cloud Console and place it at:"
    echo "      $PROJECT_DIR/credentials.json"
fi

if [[ -f "$PROJECT_DIR/token.json" ]]; then
    echo "      token.json found."
else
    echo ""
    echo "  [!] token.json not found."
    echo "      Generate it on a machine with a browser:"
    echo "        source .venv/bin/activate"
    echo "        python -m gcal_epd.main"
    echo "      Then copy token.json to this Pi:"
    echo "        scp token.json admin@<pi-ip>:$PROJECT_DIR/"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next step — install systemd timer:"
echo "  bash deploy/install.sh"
