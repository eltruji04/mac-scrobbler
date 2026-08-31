"""One-time Last.fm authentication.

Run this once, interactively:

    .venv/bin/python lastfm_auth.py

It prints a Last.fm authorization URL, opens it in your browser, waits for you to
click "Yes, allow access", and then exchanges the token for a *non-expiring*
session key which it writes to ``~/.config/mac-scrobbler/session_key``.
"""

from __future__ import annotations

import sys
import webbrowser

import pylast

import config


def main() -> int:
    api_key, api_secret = config.get_api_credentials()

    if config.load_session_key():
        ans = input(
            f"A session key already exists at {config.SESSION_KEY_FILE}.\n"
            "Overwrite it? [y/N] "
        ).strip().lower()
        if ans != "y":
            print("Keeping the existing session key. Nothing to do.")
            return 0

    network = pylast.LastFMNetwork(api_key=api_key, api_secret=api_secret)
    skg = pylast.SessionKeyGenerator(network)
    auth_url = skg.get_web_auth_url()

    print("\n1. Opening this URL in your browser (copy it manually if it doesn't open):\n")
    print("   " + auth_url + "\n")
    try:
        webbrowser.open(auth_url)
    except Exception:  # pragma: no cover
        pass

    input("2. Authorize the app in the browser, then press Enter here to continue... ")

    try:
        session_key = skg.get_web_auth_session_key(auth_url)
    except pylast.WSError as exc:  # pragma: no cover - depends on user action
        print(f"\nFailed to get a session key: {exc}", file=sys.stderr)
        print("Make sure you clicked 'Yes, allow access' before pressing Enter.")
        return 1

    config.save_session_key(session_key)
    print(f"\nSuccess. Session key saved to {config.SESSION_KEY_FILE}")
    print("You can now run:  .venv/bin/python scrobbler.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
