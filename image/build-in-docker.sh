#!/bin/bash
# Build the e-Paper calendar image from the current commit, in a privileged
# Debian container. Same command on a Mac (Docker Desktop) and in CI.
#
#   bash image/build-in-docker.sh            # → image/dist/e-pages-<version>.img.xz
#   VERSION=v1.2.0 WIFI_COUNTRY=JP bash image/build-in-docker.sh
#
# Only committed files go in (git archive HEAD); uncommitted edits do not.
set -euo pipefail

cd "$(dirname "$0")/.."
VERSION="${VERSION:-$(git describe --tags --always --dirty)}"
OUT="${OUT:-image/dist}"
mkdir -p "$OUT"
git archive --format=tar -o "$OUT/app.tar" HEAD

docker run --rm --privileged \
    -v "$PWD/image:/image:ro" -v "$PWD/$OUT:/out" \
    -e VERSION="$VERSION" -e WIFI_COUNTRY="${WIFI_COUNTRY:-TW}" \
    debian:trixie bash -c '
        set -e
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
            ca-certificates curl xz-utils fdisk e2fsprogs zerofree mtools mount > /dev/null
        bash /image/build.sh /out/app.tar /out'
rm -f "$OUT/app.tar"
