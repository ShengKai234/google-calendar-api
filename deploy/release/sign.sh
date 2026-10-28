#!/bin/bash
# Sign a published release on this Mac: the private key never leaves it,
# so a stolen GitHub token alone cannot ship code to the displays.
#
#   bash deploy/release/sign.sh v0.2.0                  # the everyday key
#   bash deploy/release/sign.sh v0.5.0 --key FILE       # e.g. the backup key
#
# Downloads every file of the release, checks each against its SHA256SUMS
# (so what you sign is what was published), signs SHA256SUMS with
# ssh-keygen and uploads SHA256SUMS.sig. Displays (and prepare.sh) accept
# a release only if that signature verifies against allowed_signers.
#
# Two keys, both listed in deploy/release/allowed_signers (see
# docs/DEPLOYMENT.md, "Signing keys"):
#   ~/.ssh/e-pages-release   everyday key, on this Mac ($EPD_SIGNING_KEY)
#   backup key               kept offline; signs only the release that
#                            replaces a lost or leaked everyday key
set -euo pipefail

REPO=ShengKai234/google-calendar-api
NAMESPACE=e-pages-release
HERE="$(cd "$(dirname "$0")" && pwd)"
SIGNERS="$HERE/allowed_signers"
KEY="${EPD_SIGNING_KEY:-$HOME/.ssh/e-pages-release}"
TAG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --key) KEY="$2"; shift 2 ;;
        -*) echo "Unknown option: $1"; exit 2 ;;
        *) TAG="$1"; shift ;;
    esac
done
[ -n "$TAG" ] || { echo "usage: sign.sh vX.Y.Z [--key FILE]"; exit 2; }

[ -f "$KEY" ] || { echo "No signing key at $KEY (see the top of this script)."; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Downloading $TAG..."
gh release download "$TAG" -R "$REPO" -D "$WORK"
rm -f "$WORK/SHA256SUMS.sig"
cd "$WORK" || exit 1
# Every published file must be listed, and every listed file must match.
listed="$(awk '{print $2}' SHA256SUMS | sort)"
present="$(find . -maxdepth 1 -type f ! -name SHA256SUMS | sed 's|^\./||' | sort)"
[ "$listed" = "$present" ] || {
    echo "SHA256SUMS and the release's files differ:"
    diff <(echo "$listed") <(echo "$present") || true
    exit 1
}
shasum -a 256 -c SHA256SUMS
cat SHA256SUMS

ssh-keygen -Y sign -f "$KEY" -n "$NAMESPACE" SHA256SUMS
# Checked against the keys this release ships: a display keeps trusting
# exactly those after installing it.
SHIPPED="$WORK/shipped_allowed_signers"
tar -xzf e-pages-*.tar.gz -O deploy/release/allowed_signers > "$SHIPPED" 2>/dev/null || \
    cp "$SIGNERS" "$SHIPPED"
ssh-keygen -Y verify -f "$SHIPPED" -I "$NAMESPACE" -n "$NAMESPACE" \
    -s SHA256SUMS.sig < SHA256SUMS > /dev/null || {
    echo "Signed, but the release's allowed_signers does not list this key."
    exit 1
}
gh release upload "$TAG" -R "$REPO" SHA256SUMS.sig --clobber
echo "Signed $TAG."
