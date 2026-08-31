#!/usr/bin/env bash
# Unload and remove the launchd agent. Leaves ~/.config/mac-scrobbler/ untouched.
set -euo pipefail

PLIST="$HOME/Library/LaunchAgents/mac-scrobbler.plist"

if [ -f "$PLIST" ]; then
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed $PLIST"
else
    echo "Nothing to do: $PLIST does not exist."
fi
