#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="gcal-epd"

echo "=== gcal-epd deploy ==="
echo "Project: $PROJECT_DIR"
echo ""

# --- 確認在 Raspberry Pi 上執行 ---
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo "Warning: This script is intended for Raspberry Pi."
    read -rp "Continue anyway? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || exit 1
fi

# --- 複製 systemd 設定檔 ---
echo "[1/4] Installing systemd units..."
sudo cp "$PROJECT_DIR/deploy/$SERVICE_NAME.service" /etc/systemd/system/
sudo cp "$PROJECT_DIR/deploy/$SERVICE_NAME.timer"   /etc/systemd/system/
echo "      Copied .service and .timer to /etc/systemd/system/"

# --- 重新載入 systemd ---
echo "[2/4] Reloading systemd daemon..."
sudo systemctl daemon-reload

# --- 啟用並啟動 timer ---
echo "[3/4] Enabling and starting timer..."
sudo systemctl enable "$SERVICE_NAME.timer"
sudo systemctl start  "$SERVICE_NAME.timer"

# --- 啟用硬體 Watchdog ---
echo "[4/4] Enabling hardware watchdog..."
BOOT_CONFIG="/boot/firmware/config.txt"
# 舊版 Pi OS 路徑
[[ -f "$BOOT_CONFIG" ]] || BOOT_CONFIG="/boot/config.txt"

if ! grep -q "dtparam=watchdog=on" "$BOOT_CONFIG"; then
    echo "dtparam=watchdog=on" | sudo tee -a "$BOOT_CONFIG" > /dev/null
    echo "      Added dtparam=watchdog=on to $BOOT_CONFIG"
else
    echo "      Watchdog already enabled in $BOOT_CONFIG"
fi

if ! dpkg -s watchdog &>/dev/null; then
    sudo apt-get install -y watchdog
fi

# --- 結果摘要 ---
echo ""
echo "=== Done ==="
systemctl status "$SERVICE_NAME.timer" --no-pager -l
echo ""
echo "Next run:"
systemctl list-timers "$SERVICE_NAME.timer" --no-pager 2>/dev/null | grep "$SERVICE_NAME" || true
echo ""
echo "Commands:"
echo "  手動執行    : sudo systemctl start $SERVICE_NAME.service"
echo "  查看 log    : journalctl -u $SERVICE_NAME.service -n 50"
echo "  停用排程    : sudo systemctl disable $SERVICE_NAME.timer"
echo ""
echo "Note: Reboot required for watchdog to take effect."
read -rp "Reboot now? [y/N] " reboot_now
[[ "$reboot_now" =~ ^[Yy]$ ]] && sudo reboot
