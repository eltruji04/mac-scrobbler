"""Configuration loading for mac-scrobbler.

Secrets are looked up in this order:

1. Environment variables ``LASTFM_API_KEY`` / ``LASTFM_API_SECRET``.
2. ``~/.config/mac-scrobbler/config.json`` -> ``{"api_key": "...", "api_secret": "..."}``.

The Last.fm session key (obtained once via ``lastfm_auth.py``) is stored in
``~/.config/mac-scrobbler/session_key``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path(
    os.environ.get("MAC_SCROBBLER_CONFIG_DIR", Path.home() / ".config" / "mac-scrobbler")
)
CONFIG_FILE = CONFIG_DIR / "config.json"
SESSION_KEY_FILE = CONFIG_DIR / "session_key"
LOG_FILE = CONFIG_DIR / "scrobbler.log"

# Polling / scrobble tuning ----------------------------------------------------
POLL_INTERVAL = int(os.environ.get("MAC_SCROBBLER_POLL_INTERVAL", "10"))  # seconds
# Last.fm "Scrobbling 2.0" rules: track must be > 30s, and played for at least
# half its length OR 4 minutes, whichever comes first.
MIN_TRACK_LENGTH = 30
SCROBBLE_MAX_THRESHOLD = 240  # 4 minutes
# Re-send "now playing" this often while a long track keeps playing (Last.fm
# expires the now-playing status roughly after the track's duration).
NOW_PLAYING_REFRESH = 120


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _load_config_file() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:  # pragma: no cover - user error
        raise SystemExit(f"{CONFIG_FILE} is not valid JSON: {exc}")


def get_api_credentials() -> tuple[str, str]:
    """Return ``(api_key, api_secret)`` or exit with a helpful message."""
    data = _load_config_file()
    api_key = os.environ.get("LASTFM_API_KEY") or data.get("api_key")
    api_secret = os.environ.get("LASTFM_API_SECRET") or data.get("api_secret")
    if not api_key or not api_secret:
        raise SystemExit(
            "Missing Last.fm API credentials.\n"
            "Create a key at https://www.last.fm/api/account/create then either:\n"
            f"  - write {CONFIG_FILE} as "
            '{"api_key": "...", "api_secret": "..."}\n'
            "  - or export LASTFM_API_KEY / LASTFM_API_SECRET"
        )
    return api_key, api_secret


def load_session_key() -> str | None:
    try:
        with open(SESSION_KEY_FILE, "r", encoding="utf-8") as fh:
            key = fh.read().strip()
            return key or None
    except FileNotFoundError:
        return None


def save_session_key(session_key: str) -> None:
    ensure_config_dir()
    with open(SESSION_KEY_FILE, "w", encoding="utf-8") as fh:
        fh.write(session_key + "\n")
    os.chmod(SESSION_KEY_FILE, 0o600)
