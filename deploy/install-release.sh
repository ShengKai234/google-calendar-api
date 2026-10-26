#!/bin/bash
# Install this checkout's HEAD as a release under /opt/e-pages and switch
# the display to it. Run on the Pi:
#
#   bash deploy/install-release.sh                      # a new release
#   bash deploy/install-release.sh --migrate-from ~/google-calendar-api
#                                    # first time: carry over feeds and settings
#
# Only committed files are installed. The running release is untouched
# until the new one is built and imports; see `python3 -m gcal_epd.releases -h`
# for list / switch / rollback.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
ARGS=("$@")
# The checkout's owner runs the app, unless --user says otherwise.
if [[ " $* " != *" --user "* ]]; then
    ARGS+=(--user "$(stat -c %U "$SRC")")
fi
exec sudo env PYTHONPATH="$SRC/src" PYTHONDONTWRITEBYTECODE=1 \
    python3 -m gcal_epd.releases install --source "$SRC" "${ARGS[@]}"
