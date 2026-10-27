#!/bin/bash
# Sign a published release on this Mac: the private key never leaves it,
# so a stolen GitHub token alone cannot ship code to the displays.
#
#   bash deploy/release/sign.sh v0.2.0
#
# Downloads every file of the release, checks each against its SHA256SUMS
# (so what you sign is what was published), signs SHA256SUMS with
# ssh-keygen and uploads SHA256SUMS.sig. Displays (and prepare.sh) accept
# a release only if that signature verifies against allowed_signers.
#
# Key: $EPD_SIGNING_KEY, default ~/.ssh/e-pages-release. Make it once:
#   ssh-keygen -t ed25519 -f ~/.ssh/e-pages-release -C e-pages-release
# and add its public half to deploy/release/allowed_signers as
#   e-pages-release namespaces="e-pages-release" ssh-ed25519 AAAA...
# (commit that line before the release is tagged, so it ships in it).
set -euo pipefail

REPO=ShengKai234/google-calendar-api
NAMESPACE=e-pages-release
HERE="$(cd "$(dirname "$0")" && pwd)"
SIGNERS="$HERE/allowed_signers"
KEY="${EPD_SIGNING_KEY:-$HOME/.ssh/e-pages-release}"
TAG="${1:?usage: sign.sh vX.Y.Z}"

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
ssh-keygen -Y verify -f "$SIGNERS" -I "$NAMESPACE" -n "$NAMESPACE" \
    -s SHA256SUMS.sig < SHA256SUMS || {
    echo "Signed, but $SIGNERS does not accept this key: add its public key there."
    exit 1
}
gh release upload "$TAG" -R "$REPO" SHA256SUMS.sig --clobber
echo "Signed $TAG."
