#!/usr/bin/env bash
# Generate ~/Library/LaunchAgents/mac-scrobbler.plist from the template (filling
# in this checkout's path and your home dir) and load it with launchd.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$HERE/mac-scrobbler.plist.template"
PLIST="$HOME/Library/LaunchAgents/mac-scrobbler.plist"

if [ ! -x "$HERE/.venv/bin/python" ]; then
    echo "error: $HERE/.venv/bin/python not found." >&2
    echo "Run first:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

mkdir -p "$HOME/.config/mac-scrobbler" "$HOME/Library/LaunchAgents"

sed -e "s|__INSTALL_DIR__|$HERE|g" -e "s|__HOME__|$HOME|g" "$TEMPLATE" > "$PLIST"
plutil -lint "$PLIST"

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"

echo "Loaded. Check with:  launchctl list | grep mac-scrobbler"
