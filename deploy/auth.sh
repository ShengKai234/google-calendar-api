#!/bin/bash
# Run the one-time calendar setup (shows QR code, waits for calendar sharing).
# Usage:
#   bash deploy/auth.sh            # terminal only
#   bash deploy/auth.sh --display  # also renders to e-ink display (Pi only)

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Activate venv
if [ -d "$PROJECT_DIR/.venv" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
elif [ -d "$PROJECT_DIR/venv" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
else
    echo "Error: no virtual environment found (.venv or venv)."
    exit 1
fi

# Check for service_account.json
if [ ! -f "$PROJECT_DIR/service_account.json" ]; then
    echo ""
    echo "Error: service_account.json not found."
    echo ""
    echo "To create one:"
    echo "  1. Go to console.cloud.google.com"
    echo "  2. IAM & Admin > Service Accounts > Create Service Account"
    echo "  3. Create Key > JSON > Download"
    echo "  4. Save as: $PROJECT_DIR/service_account.json"
    echo "  5. Enable Google Calendar API on your project"
    echo ""
    exit 1
fi

python -m gcal_epd.main --setup "$@"
