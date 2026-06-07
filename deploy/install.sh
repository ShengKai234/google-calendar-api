#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="gcal-epd"

echo "=== gcal-epd deploy ==="
echo "Project: $PROJECT_DIR"
echo ""

# --- Verify running on Raspberry Pi ---
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo "Warning: This script is intended for Raspberry Pi."
    read -rp "Continue anyway? [y/N] " confirm
    case "$confirm" in [Yy]) ;; *) exit 1 ;; esac
fi

# --- Copy systemd units ---
echo "[1/4] Installing systemd units..."
sudo cp "$PROJECT_DIR/deploy/$SERVICE_NAME.service" /etc/systemd/system/
sudo cp "$PROJECT_DIR/deploy/$SERVICE_NAME.timer"   /etc/systemd/system/
echo "      Copied .service and .timer to /etc/systemd/system/"

# --- Reload systemd ---
echo "[2/4] Reloading systemd daemon..."
sudo systemctl daemon-reload

# --- Enable and start timer ---
echo "[3/4] Enabling and starting timer..."
sudo systemctl enable "$SERVICE_NAME.timer"
sudo systemctl start  "$SERVICE_NAME.timer"

# --- Enable hardware watchdog ---
echo "[4/4] Enabling hardware watchdog..."
BOOT_CONFIG="/boot/firmware/config.txt"
# Fallback path for older Pi OS
[ -f "$BOOT_CONFIG" ] || BOOT_CONFIG="/boot/config.txt"

if ! grep -q "dtparam=watchdog=on" "$BOOT_CONFIG"; then
    echo "dtparam=watchdog=on" | sudo tee -a "$BOOT_CONFIG" > /dev/null
    echo "      Added dtparam=watchdog=on to $BOOT_CONFIG"
else
    echo "      Watchdog already enabled in $BOOT_CONFIG"
fi

if ! dpkg -s watchdog &>/dev/null; then
    sudo apt-get install -y watchdog
fi

# --- Summary ---
echo ""
echo "=== Done ==="
systemctl status "$SERVICE_NAME.timer" --no-pager -l
echo ""
echo "Next run:"
systemctl list-timers "$SERVICE_NAME.timer" --no-pager 2>/dev/null | grep "$SERVICE_NAME" || true
echo ""
echo "Commands:"
echo "  Manual run  : sudo systemctl start $SERVICE_NAME.service"
echo "  View logs   : journalctl -u $SERVICE_NAME.service -n 50"
echo "  Disable     : sudo systemctl disable $SERVICE_NAME.timer"
echo ""
echo "Note: Reboot required for watchdog to take effect."
read -rp "Reboot now? [y/N] " reboot_now
case "$reboot_now" in [Yy]) sudo reboot ;; esac
