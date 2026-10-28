#!/bin/bash
# First boot of a new card: install the e-Paper calendar with no network.
#
# Ships in the SD card bundle (epd-bundle/ on the boot partition, next to
# app.tar.gz, wheels/ and debs/) and is run once by cloud-init, from the
# runcmd line deploy/sdcard/prepare.sh adds to user-data:
#
#   env EPD_USER=<the account Imager made> bash /boot/firmware/epd-bundle/firstboot.sh
#
# cloud-init then reboots (power_state in user-data, once this script has
# written its done-file), and the Pi comes up in Wi-Fi setup.
#
# Log: /var/log/epd-firstboot.log, also copied to the boot partition, so a
# Mac or PC can read it with the card out of the Pi. Feed URLs are never in
# it: a new card has none yet.
set -euo pipefail
LOG_COPY=/boot/firmware/epd-firstboot.log
exec > >(tee -a /var/log/epd-firstboot.log "$LOG_COPY") 2>&1
trap 'echo "FAILED (exit $?) at line $LINENO: $BASH_COMMAND"; sync' ERR
echo "=== epd-firstboot $(date) ==="

BUNDLE="$(cd "$(dirname "$0")" && pwd)"
DONE=/var/lib/epd-firstboot.done
[ -f "$DONE" ] && { echo "Already installed."; exit 0; }

RUN_USER="${EPD_USER:?EPD_USER is not set: say which user runs the app}"
getent passwd "$RUN_USER" > /dev/null || { echo "No user $RUN_USER on this card."; exit 1; }
echo "User: $RUN_USER  Bundle: $BUNDLE"

echo "[1/3] System libraries for Pillow, watchdog and the PiSugar daemon..."
# PiSugar's packages ask these at install. Its defaults would serve a web
# page that can power the Pi off, to the whole network, with no password:
# here it listens on 127.0.0.1 only (gcal_epd.power_manager uses TCP 8423).
# On a Pi without a PiSugar the daemon finds no board and the power
# manager keeps the Pi always on.
debconf-set-selections <<'SEL'
pisugar-server pisugar-server/model select PiSugar 3
pisugar-server pisugar-server/address select 127.0.0.1
pisugar-server pisugar-server/web boolean false
pisugar-server pisugar-server/tcp boolean true
pisugar-server pisugar-server/uds boolean false
pisugar-poweroff pisugar-poweroff/model select PiSugar 3
SEL
DEBIAN_FRONTEND=noninteractive dpkg -i "$BUNDLE"/debs/*.deb
# Their scripts enable a service only when it was enabled before.
systemctl enable pisugar-server.service pisugar-poweroff.service

echo "[2/3] The calendar, as a release under /opt/e-pages (takes a few minutes)..."
# The installer is part of the release it installs: run it from a copy.
SRC="$(mktemp -d)"
# -m: a new card's clock still says when its image was built, so every
# file's real time would be "in the future" (one warning each).
tar -xzmf "$BUNDLE/app.tar.gz" -C "$SRC"
# PYTHONPATH reaches only the installer; it keeps it from the new release.
env PYTHONPATH="$SRC/src" PYTHONDONTWRITEBYTECODE=1 \
    python3 -m gcal_epd.releases install \
        --source "$BUNDLE/app.tar.gz" --wheels "$BUNDLE/wheels" --user "$RUN_USER"
rm -rf "$SRC"

echo "[3/3] Done; cloud-init reboots into Wi-Fi setup."
touch "$DONE"
echo "=== done $(date) ==="
sync
