#!/bin/bash
# Make a card fresh from Raspberry Pi Imager install the calendar at first
# boot, with no network. Run on the Mac (or Linux PC) the card is plugged
# into, after Imager wrote it and before it ever boots:
#
#   bash deploy/sdcard/prepare.sh --release v0.2.0     # a published release
#   bash deploy/sdcard/prepare.sh --bundle dist/<label>/e-pages-<label>-sdcard.zip
#                                                     # a local build
# Options:
#   --boot DIR        the card's boot partition (default: /Volumes/bootfs,
#                     else /media/$USER/bootfs)
#   --country CC      Wi-Fi country for the hotspot (default: TW)
#   --allow-unsigned  accept a release whose SHA256SUMS is not signed yet
#
# It copies epd-bundle/ to the boot partition, turns SPI on, sets the Wi-Fi
# country, and adds to cloud-init's user-data: run epd-bundle/firstboot.sh
# as the user Imager created, then reboot. See docs/DEPLOYMENT.md.
set -euo pipefail

REPO=ShengKai234/google-calendar-api
HERE="$(cd "$(dirname "$0")" && pwd)"
SIGNERS="$HERE/../release/allowed_signers"
NAMESPACE=e-pages-release
FIRSTBOOT=/boot/firmware/epd-bundle/firstboot.sh
DONE_FILE=/var/lib/epd-firstboot.done

BOOT=""; RELEASE=""; BUNDLE=""; COUNTRY=TW; ALLOW_UNSIGNED=no
while [ $# -gt 0 ]; do
    case "$1" in
        --boot) BOOT="$2"; shift 2 ;;
        --release) RELEASE="$2"; shift 2 ;;
        --bundle) BUNDLE="$2"; shift 2 ;;
        --country) COUNTRY="$2"; shift 2 ;;
        --allow-unsigned) ALLOW_UNSIGNED=yes; shift ;;
        -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1 (see --help)"; exit 2 ;;
    esac
done
die() { echo "Error: $*" >&2; exit 1; }

# --- the card ---------------------------------------------------------------
if [ -z "$BOOT" ]; then
    for d in /Volumes/bootfs "/media/${USER:-}/bootfs"; do
        [ -d "$d" ] && { BOOT="$d"; break; }
    done
fi
[ -n "$BOOT" ] && [ -d "$BOOT" ] || die "no boot partition found; plug the card in or pass --boot DIR."
for f in config.txt cmdline.txt user-data; do
    [ -f "$BOOT/$f" ] || die "$BOOT/$f is missing: is this a Raspberry Pi OS card written by Imager?"
done
# cloud-init runs user-data once per card; after that, edits here do nothing.
[ -e "$BOOT/epd-firstboot.log" ] && \
    die "this card has booted before (epd-firstboot.log). Write it again with Imager first."
[[ "$COUNTRY" =~ ^[A-Z]{2}$ ]] || die "--country wants two capital letters, like TW."

# The account Imager created: the app runs as it.
RUN_USER="$(awk '/^user:/ {u=1; next} u && /^[^[:space:]]/ {u=0}
                 u && $1 == "name:" {gsub(/["'\'']/, "", $2); print $2; exit}' "$BOOT/user-data")"
[ -n "$RUN_USER" ] || die "user-data names no user: set a username in Imager's settings."
echo "Card     : $BOOT"
echo "App user : $RUN_USER"

# --- the bundle -------------------------------------------------------------
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [ -n "$RELEASE" ]; then
    [ -z "$BUNDLE" ] || die "give --release or --bundle, not both."
    command -v gh > /dev/null || die "--release needs the GitHub CLI (gh)."
    echo "Release  : $RELEASE (downloading...)"
    gh release download "$RELEASE" -R "$REPO" -D "$WORK" --clobber \
        -p '*-sdcard.zip' -p SHA256SUMS -p SHA256SUMS.sig 2>/dev/null || \
        gh release download "$RELEASE" -R "$REPO" -D "$WORK" --clobber -p '*-sdcard.zip' -p SHA256SUMS
    if [ -f "$WORK/SHA256SUMS.sig" ]; then
        grep -q '^[^#[:space:]]' "$SIGNERS" 2>/dev/null || \
            die "$SIGNERS has no key to check the signature with."
        ssh-keygen -Y verify -f "$SIGNERS" -I "$NAMESPACE" -n "$NAMESPACE" \
            -s "$WORK/SHA256SUMS.sig" < "$WORK/SHA256SUMS" > /dev/null || \
            die "SHA256SUMS of $RELEASE is NOT signed by a key in $SIGNERS."
        echo "Signature: good"
    elif [ "$ALLOW_UNSIGNED" = yes ]; then
        echo "Signature: none (--allow-unsigned)"
    else
        die "$RELEASE is not signed yet (deploy/release/sign.sh); or pass --allow-unsigned."
    fi
    BUNDLE="$(ls "$WORK"/*-sdcard.zip)"
    want="$(awk -v n="$(basename "$BUNDLE")" '$2 == n {print $1}' "$WORK/SHA256SUMS")"
    got="$(shasum -a 256 "$BUNDLE" | cut -d' ' -f1)"
    [ -n "$want" ] && [ "$want" = "$got" ] || die "$(basename "$BUNDLE") does not match SHA256SUMS."
    echo "Checksum : good"
fi
[ -n "$BUNDLE" ] || die "say what to install: --release vX.Y.Z or --bundle FILE.zip"
[ -f "$BUNDLE" ] || die "$BUNDLE not found."
echo "Bundle   : $(basename "$BUNDLE")"

unzip -q "$BUNDLE" -d "$WORK/unzipped"
B="$WORK/unzipped/epd-bundle"
for f in app.tar.gz firstboot.sh wheels debs; do
    [ -e "$B/$f" ] || die "the bundle has no epd-bundle/$f."
done

# --- onto the card ----------------------------------------------------------
echo "[1/4] Copying epd-bundle/ ($(du -sh "$B" | cut -f1))..."
rm -rf "$BOOT/epd-bundle"
# COPYFILE_DISABLE: no macOS ._ files on the FAT partition.
COPYFILE_DISABLE=1 cp -R "$B" "$BOOT/epd-bundle"
find "$BOOT/epd-bundle" -name '._*' -delete

# Rewrite a file in place (keeps its owner and mode, works on FAT).
rewrite() { cat "$2" > "$1"; }

echo "[2/4] SPI on (the panel)..."
CONFIG="$BOOT/config.txt"
if ! grep -q '^dtparam=spi=on' "$CONFIG"; then
    if grep -q '^#dtparam=spi=on' "$CONFIG"; then
        sed 's/^#dtparam=spi=on/dtparam=spi=on/' "$CONFIG" > "$WORK/config.txt"
    else
        { cat "$CONFIG"; printf '\n[all]\ndtparam=spi=on\n'; } > "$WORK/config.txt"
    fi
    rewrite "$CONFIG" "$WORK/config.txt"
fi

echo "[3/4] Wi-Fi country $COUNTRY..."
CMDLINE="$BOOT/cmdline.txt"
# One line only: the kernel reads nothing past the first.
if ! grep -q 'cfg80211.ieee80211_regdom=' "$CMDLINE"; then
    printf '%s cfg80211.ieee80211_regdom=%s\n' "$(head -n1 "$CMDLINE" | tr -d '\r\n')" \
        "$COUNTRY" > "$WORK/cmdline.txt"
    rewrite "$CMDLINE" "$WORK/cmdline.txt"
fi

echo "[4/4] First-boot install in user-data..."
USER_DATA="$BOOT/user-data"
if grep -qF "$FIRSTBOOT" "$USER_DATA"; then
    echo "      Already there."
else
    if grep -q '^runcmd:' "$USER_DATA" && ! grep -q '^runcmd:[[:space:]]*$' "$USER_DATA"; then
        die "user-data's runcmd is not a block list; add the firstboot line by hand (docs/DEPLOYMENT.md)."
    fi
    grep -q '^power_state:' "$USER_DATA" && \
        die "user-data already has a power_state; merge the reboot by hand (docs/DEPLOYMENT.md)."
    ITEM="[ env, EPD_USER=$RUN_USER, bash, $FIRSTBOOT ]"
    # Last in runcmd (after Imager's own commands), at the list's own indent.
    awk -v item="$ITEM" '
        function add() { if (!added) { print ind "# e-Paper calendar: offline install (log: /var/log/epd-firstboot.log)";
                                         print ind "- " item; added = 1 } }
        /^runcmd:[[:space:]]*$/ { print; inrun = 1; ind = "  "; seen = 0; next }
        inrun && /^[^[:space:]#-]/ { add(); inrun = 0 }
        inrun && !seen && /^[[:space:]]*- / { match($0, /^[[:space:]]*/); ind = substr($0, 1, RLENGTH); seen = 1 }
        { print }
        END { if (inrun) add(); else if (!added) { print "runcmd:"; ind = "  "; add() } }
    ' "$USER_DATA" > "$WORK/user-data"
    cat >> "$WORK/user-data" <<EOF
# Reboot into Wi-Fi setup once the calendar is installed.
power_state:
  mode: reboot
  condition: test -f $DONE_FILE
EOF
    rewrite "$USER_DATA" "$WORK/user-data"
fi
if python3 -c 'import yaml' 2>/dev/null; then
    python3 -c 'import sys, yaml; d = yaml.safe_load(open(sys.argv[1]));
assert any("firstboot" in str(c) for c in d["runcmd"]) and d["power_state"]["mode"] == "reboot"' \
        "$USER_DATA" || die "user-data is no longer valid; write the card again with Imager."
    echo "      user-data checked."
fi

sync
echo ""
echo "Done. Eject the card, put it in the Pi and power it on. The first boot"
echo "installs the calendar (about 10 minutes on a Pi Zero), reboots, and the"
echo "panel shows the Wi-Fi setup QR code. If it does not, read"
echo "epd-firstboot.log on this partition (put the card back in this computer)."
