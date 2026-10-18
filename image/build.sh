#!/bin/bash
# Build a ready-to-flash Raspberry Pi OS image with the calendar preinstalled:
# packages, .venv and systemd units are all in place, so the Pi's first boot
# goes straight to the Wi-Fi setup screen. Nothing is installed on the Pi.
#
# Runs as root on Linux with ARM emulation (binfmt) — in practice a
# privileged Debian container started by image/build-in-docker.sh.
#
# Usage: build.sh <app.tar> <output dir>
#   app.tar      the checkout to install (git archive of the release commit)
#   output dir   gets e-pages-<VERSION>.img.xz and its .sha256
# Environment: VERSION (default dev), WIFI_COUNTRY (default TW),
#              CACHE (default <output dir>/cache, keeps the base image)
set -euo pipefail
# The boot partition is read through a loop device, not a disk mtools knows.
export MTOOLS_SKIP_CHECK=1

HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/base.env"

APP_TAR="$(realpath "$1")"
OUT="$(realpath "$2")"
VERSION="${VERSION:-dev}"
WIFI_COUNTRY="${WIFI_COUNTRY:-TW}"
CACHE="${CACHE:-$OUT/cache}"
# Room for the extra packages and the .venv; the Pi grows the root
# partition to fill the card on first boot anyway.
GROW_MB=768

# The checkout lives outside any home: the image has no login user yet
# (Raspberry Pi Imager adds one at first boot, if asked to), so the units
# run as a system user that owns the checkout.
APP_DIR=/opt/e-pages
APP_USER=epd

# Pillow's wheel from piwheels links against these; Pi OS Lite lacks them.
PILLOW_LIBS="libfreetype6 libopenjp2-7 liblcms2-2 libwebpdemux2 libwebpmux3
             libavif16 libaom3 libdav1d7 libgav1-1 librav1e0.7 libsvtav1enc2 libyuv0"

IMG="$OUT/e-pages-$VERSION.img"
ROOT="$(mktemp -d)"
LOOPS=()

cleanup() {
    set +e
    umount -R "$ROOT" 2>/dev/null
    for loop in "${LOOPS[@]}"; do losetup -d "$loop"; done
    rmdir "$ROOT"
}
trap cleanup EXIT

step() { echo; echo "=== $* ==="; }

# Emulate the Pi Zero's ARMv6 CPU. qemu's default is ARMv7, and pip would
# then pick armv7l wheels that crash on a Pi Zero with "Illegal instruction".
in_root() { QEMU_CPU=arm1176 chroot "$ROOT" "$@"; }

step "Base image"
mkdir -p "$CACHE"
BASE="$CACHE/$(basename "$BASE_URL")"
if [ ! -f "$BASE" ]; then
    curl -fL --retry 3 -o "$BASE.part" "$BASE_URL"
    mv "$BASE.part" "$BASE"
fi
echo "$BASE_SHA256  $BASE" | sha256sum -c -
xz -dc "$BASE" > "$IMG"

step "Grow the root partition by ${GROW_MB}MB"
truncate -s "+${GROW_MB}M" "$IMG"
echo ", +" | sfdisk -q --no-reread -N 2 "$IMG"
# One loop device per partition, by offset: a container has no udev to
# create /dev/loopNpM for a partitioned loop device.
part_loop() {
    local start size
    read -r start size < <(sfdisk -d "$IMG" | \
        sed -n "s|^$IMG$1 : start= *\([0-9]*\), size= *\([0-9]*\).*|\1 \2|p")
    losetup -f --show -o $((start * 512)) --sizelimit $((size * 512)) "$IMG"
}
BOOT_LOOP="$(part_loop 1)"; LOOPS+=("$BOOT_LOOP")
ROOT_LOOP="$(part_loop 2)"; LOOPS+=("$ROOT_LOOP")
e2fsck -fy "$ROOT_LOOP" || [ $? -le 1 ]
resize2fs "$ROOT_LOOP"

step "Mount"
mount "$ROOT_LOOP" "$ROOT"
# The boot partition is FAT, which Docker Desktop's kernel cannot mount.
# Work on a copy of the two files the build changes (install.sh edits
# config.txt) and write them back with mtools at the end.
BOOT_FILES=(config.txt cmdline.txt)
BOOT_COPY="$OUT/bootfs"
rm -rf "$BOOT_COPY"; mkdir -p "$BOOT_COPY"
for f in "${BOOT_FILES[@]}"; do mcopy -n -i "$BOOT_LOOP" "::/$f" "$BOOT_COPY/$f"; done
mount --bind "$BOOT_COPY" "$ROOT/boot/firmware"
mount -t proc proc "$ROOT/proc"
mount -t sysfs sys "$ROOT/sys"
mount --bind /dev "$ROOT/dev"
mount --bind /dev/pts "$ROOT/dev/pts"
# install.sh checks it is on a Pi; the build host's cpuinfo says otherwise.
echo "Model		: Raspberry Pi (e-pages image build)" > "$OUT/cpuinfo"
mount --bind "$OUT/cpuinfo" "$ROOT/proc/cpuinfo"
mv "$ROOT/etc/resolv.conf" "$ROOT/etc/resolv.conf.epd-build" 2>/dev/null || true
cp /etc/resolv.conf "$ROOT/etc/resolv.conf"
# No service may start inside the chroot while packages install.
printf '#!/bin/sh\nexit 101\n' > "$ROOT/usr/sbin/policy-rc.d"
chmod +x "$ROOT/usr/sbin/policy-rc.d"

arch="$(in_root uname -m)"
if [ "$arch" != armv6l ]; then
    echo "Error: the chroot reports $arch, not armv6l; QEMU_CPU did not apply."
    exit 1
fi

step "System packages"
in_root apt-get update -q
# shellcheck disable=SC2086
in_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends \
    watchdog $PILLOW_LIBS

step "Program, as $APP_USER in $APP_DIR"
in_root useradd --system --home-dir "$APP_DIR" --no-create-home \
    --shell /usr/sbin/nologin --groups spi,gpio "$APP_USER"
mkdir -p "$ROOT$APP_DIR"
tar -xf "$APP_TAR" -C "$ROOT$APP_DIR"
in_root chown -R "$APP_USER:" "$APP_DIR"

step "Python environment (what deploy/setup.sh does on a Pi)"
as_app() { in_root runuser -u "$APP_USER" -- env HOME="$APP_DIR" PIP_NO_CACHE_DIR=1 "$@"; }
as_app python3 -m venv "$APP_DIR/.venv"
# Pi OS's /etc/pip.conf adds piwheels, so the wheels are prebuilt for ARMv6.
as_app "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" spidev gpiozero
as_app "$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR"
as_app "$APP_DIR/.venv/bin/python" -m compileall -q "$APP_DIR/src"
as_app "$APP_DIR/.venv/bin/python" -c \
    'import PIL._imagingft, spidev, gpiozero, gcal_epd.main, gcal_epd.wifi_setup'

step "SPI on, Wi-Fi country $WIFI_COUNTRY"
CONFIG="$ROOT/boot/firmware/config.txt"
sed -i 's/^#\?dtparam=spi=.*/dtparam=spi=on/' "$CONFIG"
grep -q '^dtparam=spi=on' "$CONFIG" || echo "dtparam=spi=on" >> "$CONFIG"
CMDLINE="$ROOT/boot/firmware/cmdline.txt"
grep -q 'cfg80211.ieee80211_regdom=' "$CMDLINE" || \
    sed -i "1s/\$/ cfg80211.ieee80211_regdom=$WIFI_COUNTRY/" "$CMDLINE"
# Pi OS keeps Wi-Fi soft-blocked until a country is set through its own
# tools; the hotspot must come up on a card nobody has configured.
mkdir -p "$ROOT/etc/systemd/system/epd-wifi-setup.service.d"
cat > "$ROOT/etc/systemd/system/epd-wifi-setup.service.d/10-image.conf" <<'EOF'
# Added by image/build.sh: the hotspot needs the radio unblocked.
[Service]
ExecStartPre=-/usr/sbin/rfkill unblock wifi
EOF

step "systemd units, timer, watchdog (deploy/install.sh)"
# install.sh is written for a running Pi. In the chroot, sudo is not needed,
# and starting or querying units is meaningless (systemd is not running);
# enabling them only writes symlinks, which works offline.
SHIMS="$ROOT/tmp/epd-shims"
mkdir -p "$SHIMS"
printf '#!/bin/sh\nexec "$@"\n' > "$SHIMS/sudo"
cat > "$SHIMS/systemctl" <<'EOF'
#!/bin/sh
case "$1" in
    start|status|daemon-reload|list-timers) exit 0 ;;
    *) exec /usr/bin/systemctl "$@" ;;
esac
EOF
chmod +x "$SHIMS"/*
# "n": do not reboot at the end.
echo n | in_root env PATH="/tmp/epd-shims:$PATH" PYTHONDONTWRITEBYTECODE=1 \
    bash -c "cd $APP_DIR && bash deploy/install.sh"
in_root systemctl is-enabled gcal-epd.timer epd-wifi-setup.service watchdog.service

step "Clean up"
in_root apt-get clean
rm -rf "$ROOT"/var/lib/apt/lists/* "$SHIMS" "$ROOT/usr/sbin/policy-rc.d"
rm -f "$ROOT/etc/resolv.conf"
mv "$ROOT/etc/resolv.conf.epd-build" "$ROOT/etc/resolv.conf" 2>/dev/null || true
echo "$VERSION" > "$ROOT$APP_DIR/IMAGE_VERSION"
in_root chown "$APP_USER:" "$APP_DIR/IMAGE_VERSION"
umount -R "$ROOT"
rm -f "$OUT/cpuinfo"
extra="$(cd "$BOOT_COPY" && ls | grep -vxF -e config.txt -e cmdline.txt || true)"
if [ -n "$extra" ]; then
    echo "Error: the build wrote to the boot partition beyond config.txt/cmdline.txt:"
    echo "$extra"
    exit 1
fi
for f in "${BOOT_FILES[@]}"; do mcopy -o -i "$BOOT_LOOP" "$BOOT_COPY/$f" "::/$f"; done
rm -rf "$BOOT_COPY"
e2fsck -fy "$ROOT_LOOP" || [ $? -le 1 ]
# Zero the free blocks, so the compressed image carries no deleted files.
zerofree "$ROOT_LOOP"
for loop in "${LOOPS[@]}"; do losetup -d "$loop"; done
LOOPS=()

step "Compress"
xz -T0 -6 -f "$IMG"
(cd "$OUT" && sha256sum "$(basename "$IMG").xz" > "$(basename "$IMG").xz.sha256")
ls -lh "$IMG.xz"
echo "Done: $IMG.xz"
