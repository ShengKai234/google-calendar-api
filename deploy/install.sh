#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="gcal-epd"
# --yes: ask nothing, and do not offer to reboot at the end, for callers
# with no one at the keyboard (gcal_epd.releases, the first-boot script).
ASSUME_YES=no
[ "${1:-}" = "--yes" ] && ASSUME_YES=yes
# The paths below are asked of this directory's own app; an inherited
# PYTHONPATH would make python answer for some other copy of it.
unset PYTHONPATH PYTHONHOME

echo "=== gcal-epd deploy ==="
echo "Project: $PROJECT_DIR"
echo ""

# --- Verify running on Raspberry Pi ---
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null && [ "$ASSUME_YES" = no ]; then
    echo "Warning: This script is intended for Raspberry Pi."
    read -rp "Continue anyway? [y/N] " confirm
    case "$confirm" in [Yy]) ;; *) exit 1 ;; esac
fi

# --- Values the unit templates need ---
# The units are templates: the paths and user below are filled in here, so
# the checkout can live anywhere and belong to any user.
PYTHON="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "Error: $PYTHON not found — run deploy/setup.sh first."
    exit 1
fi
# The app runs as whoever owns its data: the checkout itself, or an
# installed release's data/ (the release's code belongs to root).
DATA_DIR="$(cd "$PROJECT_DIR" && "$PYTHON" -c 'from gcal_epd.config import DATA_DIR; print(DATA_DIR)')"
RUN_USER="${EPD_USER:-$(stat -c %U "$DATA_DIR")}"
# Ask the app itself, so the units and config.toml's feeds_file never disagree.
FEEDS_FILE="$(cd "$PROJECT_DIR" && "$PYTHON" -c \
    'from gcal_epd.config import feeds_file, load_config; print(feeds_file(load_config()))')"
PENDING_FILE="$(cd "$PROJECT_DIR" && "$PYTHON" -c \
    'from gcal_epd.config import feeds_file, load_config
from gcal_epd.infrastructure.feeds_file import pending_feeds_path
print(pending_feeds_path(feeds_file(load_config())))')"
SCHEDULE_FILE="$(cd "$PROJECT_DIR" && "$PYTHON" -c \
    'from gcal_epd.config import schedule_file, load_config; print(schedule_file(load_config()))')"

for value in "$PROJECT_DIR" "$FEEDS_FILE" "$PENDING_FILE" "$SCHEDULE_FILE"; do
    case "$value" in
        *[[:space:]]*|*"|"*)
            echo "Error: '$value' contains a space or '|'; systemd units cannot use it as is."
            exit 1 ;;
    esac
done

echo "      Project : $PROJECT_DIR"
echo "      User    : $RUN_USER"
echo "      Data    : $DATA_DIR"
echo "      Feeds   : $FEEDS_FILE"
echo "      Pending : $PENDING_FILE"
echo "      Schedule: $SCHEDULE_FILE"

install_unit() {
    local name="$1"
    local rendered
    # The first two lines are the template note; the installed unit drops them.
    rendered="$(sed -e '1,2{/^# /d;}' \
                    -e "s|@PROJECT_DIR@|$PROJECT_DIR|g" \
                    -e "s|@USER@|$RUN_USER|g" \
                    -e "s|@FEEDS_FILE@|$FEEDS_FILE|g" \
                    -e "s|@PENDING_FILE@|$PENDING_FILE|g" \
                    -e "s|@SCHEDULE_FILE@|$SCHEDULE_FILE|g" \
                    "$PROJECT_DIR/deploy/$name")"
    if grep -q "@[A-Z_]*@" <<< "$rendered"; then
        echo "Error: deploy/$name has a placeholder this script does not fill."
        exit 1
    fi
    printf '%s\n' "$rendered" | sudo tee "/etc/systemd/system/$name" > /dev/null
}

# --- Install systemd units ---
echo "[1/4] Installing systemd units..."
install_unit "$SERVICE_NAME.service"
install_unit "$SERVICE_NAME.timer"
install_unit epd-wifi-setup.service
# Not enabled on its own: epd-wifi-setup starts it at boot when no feeds exist.
install_unit epd-feed-setup.service
# Power manager: with a PiSugar, wake-up alarm and power-off; without one it
# does nothing. The path unit moves the timer when the schedule changes.
install_unit epd-power.service
install_unit epd-power-schedule.service
install_unit epd-power-schedule.path
echo "      Installed $SERVICE_NAME.service/.timer, epd-wifi-setup, epd-feed-setup and epd-power"
# Over-the-air updates replace an installed release (RELEASE marks one);
# a git checkout is updated with git, so it gets no update timer.
if [ -f "$PROJECT_DIR/RELEASE" ]; then
    install_unit epd-update.service
    install_unit epd-update.timer
    echo "      Installed epd-update.service/.timer (over-the-air updates)"
    UPDATES=yes
else
    UPDATES=no
fi

# --- Reload systemd ---
echo "[2/4] Reloading systemd daemon..."
sudo systemctl daemon-reload

# --- Enable and start timer ---
echo "[3/4] Enabling and starting timer..."
sudo systemctl enable "$SERVICE_NAME.timer"
sudo systemctl start  "$SERVICE_NAME.timer"
# Runs at the next boot: a hotspot for Wi-Fi setup if no network is joined.
sudo systemctl enable epd-wifi-setup.service
if [ "$UPDATES" = yes ]; then
    sudo systemctl enable epd-update.timer
    sudo systemctl start  epd-update.timer
fi
# Runs at the next boot: RTC clock, then power-off after the refresh (PiSugar only).
sudo systemctl enable epd-power.service
# Already running (an update, or a reinstall): carry on with this code. It
# waits out a running update and the refresh that follows it.
sudo systemctl try-restart epd-power.service
sudo systemctl enable --now epd-power-schedule.path
# The timer follows the power schedule's times from now on, not just after a boot.
(cd "$PROJECT_DIR" && sudo env PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -m gcal_epd.power_manager apply-schedule) \
    || echo "      Warning: could not apply the power schedule to $SERVICE_NAME.timer"

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
echo "  Manual run  : .venv/bin/python -m gcal_epd.main --display"
echo "                or: sudo systemctl start $SERVICE_NAME.service"
echo "  View logs   : journalctl -u $SERVICE_NAME.service -n 50"
echo "  Disable     : sudo systemctl disable $SERVICE_NAME.timer"
echo "  Power status: $PYTHON -m gcal_epd.power_manager status"
echo "  Stay awake  : create an empty file epd-stay-awake on the boot partition"
echo "                (/boot/firmware/epd-stay-awake); the PiSugar then never powers the Pi off."
echo "  Change Wi-Fi: sudo systemd-run --working-directory=$PROJECT_DIR \\"
echo "                  $PROJECT_DIR/.venv/bin/python -m gcal_epd.wifi_setup --display --force \\"
echo "                  --start-unit gcal-epd.service --start-unit epd-feed-setup.service"
echo "                (systemd-run, so it survives the SSH session dropping with the Wi-Fi;"
echo "                 --start-unit, so links entered on the form get checked.)"
echo ""
echo "Note: Reboot required for watchdog to take effect."
[ "$ASSUME_YES" = yes ] && exit 0
read -rp "Reboot now? [y/N] " reboot_now
case "$reboot_now" in [Yy]) sudo reboot ;; esac
