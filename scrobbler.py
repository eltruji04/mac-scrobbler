"""Long-running loop: watch Music.app and report plays to Last.fm.

Run manually:

    .venv/bin/python scrobbler.py

or under launchd (see ./install-agent.sh).
"""

from __future__ import annotations

import logging
import logging.handlers
import signal
import sys
import time
from dataclasses import dataclass, field

import pylast

import config
from music_app import MusicAppError, Track, get_current_track

log = logging.getLogger("mac-scrobbler")


def setup_logging() -> None:
    config.ensure_config_dir()
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    fh = logging.handlers.RotatingFileHandler(
        config.LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    log.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)


def build_network() -> pylast.LastFMNetwork:
    api_key, api_secret = config.get_api_credentials()
    session_key = config.load_session_key()
    if not session_key:
        raise SystemExit(
            "No Last.fm session key. Run:  .venv/bin/python lastfm_auth.py"
        )
    return pylast.LastFMNetwork(
        api_key=api_key, api_secret=api_secret, session_key=session_key
    )


@dataclass
class PlayState:
    """Tracks progress of the song currently being watched."""

    identity: str
    artist: str
    title: str
    album: str
    album_artist: str
    duration: float
    track_number: int
    start_timestamp: int
    listened: float = 0.0          # observed seconds of playback
    last_position: float = 0.0
    now_playing_sent_at: float = 0.0  # monotonic clock
    scrobbled: bool = False

    @property
    def scrobble_threshold(self) -> float:
        return min(self.duration / 2.0, config.SCROBBLE_MAX_THRESHOLD)

    @property
    def eligible_length(self) -> bool:
        return self.duration > config.MIN_TRACK_LENGTH


class Scrobbler:
    def __init__(self, network: pylast.LastFMNetwork) -> None:
        self.network = network
        self.current: PlayState | None = None
        self._running = True

    # -- lifecycle ----------------------------------------------------------
    def stop(self, *_a) -> None:
        self._running = False

    def run(self) -> None:
        log.info("mac-scrobbler started (poll every %ss)", config.POLL_INTERVAL)
        while self._running:
            try:
                self.tick()
            except MusicAppError as exc:
                log.warning("Music.app read failed: %s", exc)
            except Exception:  # noqa: BLE001 - keep the daemon alive
                log.exception("unexpected error in tick()")
            # responsive shutdown
            for _ in range(config.POLL_INTERVAL):
                if not self._running:
                    break
                time.sleep(1)
        log.info("mac-scrobbler stopped")

    # -- core -------------------------------------------------------------
    def tick(self) -> None:
        track = get_current_track()
        now = time.monotonic()

        if not track.is_active:
            self.current = None
            return

        if track.state == "paused":
            # Keep the PlayState around (so resuming continues progress) but
            # don't accrue time or refresh now-playing.
            if self.current and self.current.identity == track.identity:
                self.current.last_position = track.position
            return

        # state == "playing" from here on
        if self.current is None or self.current.identity != track.identity:
            self._begin(track, now)
            return

        # Same track, still playing: detect a restart / large seek-back.
        if track.position < self.current.last_position - 10:
            log.info("restart/seek-back detected for %s", self._label(track))
            self._begin(track, now)
            return

        self._advance(track, now)

    # -- helpers --------------------------------------------------------
    def _begin(self, track: Track, now: float) -> None:
        started = int(time.time() - min(track.position, track.duration or track.position))
        self.current = PlayState(
            identity=track.identity,
            artist=track.artist,
            title=track.name,
            album=track.album,
            album_artist=track.album_artist,
            duration=track.duration,
            track_number=track.track_number,
            start_timestamp=started,
            last_position=track.position,
        )
        log.info(
            "now playing: %s  (%.0fs)%s",
            self._label(track),
            track.duration,
            "" if self.current.eligible_length else "  [too short to scrobble]",
        )
        self._send_now_playing(self.current, now)

    def _advance(self, track: Track, now: float) -> None:
        ps = self.current
        assert ps is not None

        # Credit observed playback using the position delta (only advances while
        # actually playing); cap it so a forward seek can't over-credit.
        pos_delta = track.position - ps.last_position
        if 0 < pos_delta <= config.POLL_INTERVAL * 2 + 2:
            ps.listened += pos_delta
        ps.last_position = track.position

        if (
            not ps.scrobbled
            and ps.eligible_length
            and ps.listened >= ps.scrobble_threshold
        ):
            self._send_scrobble(ps)

        # Refresh now-playing for long tracks.
        if (
            not ps.scrobbled
            and now - ps.now_playing_sent_at >= config.NOW_PLAYING_REFRESH
        ):
            self._send_now_playing(ps, now)

    def _send_now_playing(self, ps: PlayState, now: float) -> None:
        try:
            self.network.update_now_playing(
                artist=ps.artist,
                title=ps.title,
                album=ps.album or None,
                album_artist=ps.album_artist or None,
                duration=int(ps.duration) or None,
                track_number=ps.track_number or None,
            )
            ps.now_playing_sent_at = now
        except (pylast.WSError, pylast.NetworkError, pylast.MalformedResponseError) as exc:
            log.warning("update_now_playing failed (%s): %s", ps.title, exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("update_now_playing error (%s): %s", ps.title, exc)

    def _send_scrobble(self, ps: PlayState) -> None:
        try:
            self.network.scrobble(
                artist=ps.artist,
                title=ps.title,
                timestamp=ps.start_timestamp,
                album=ps.album or None,
                album_artist=ps.album_artist or None,
                duration=int(ps.duration) or None,
                track_number=ps.track_number or None,
            )
            ps.scrobbled = True
            log.info(
                "scrobbled: %s — %s  (listened %.0fs / threshold %.0fs)",
                ps.artist,
                ps.title,
                ps.listened,
                ps.scrobble_threshold,
            )
        except (pylast.WSError, pylast.NetworkError, pylast.MalformedResponseError) as exc:
            log.warning("scrobble failed (%s), will retry next tick: %s", ps.title, exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("scrobble error (%s), will retry next tick: %s", ps.title, exc)

    @staticmethod
    def _label(track: Track) -> str:
        return f"{track.artist} — {track.name}"


def main() -> int:
    setup_logging()
    try:
        network = build_network()
    except SystemExit as exc:
        log.error("%s", exc)
        raise

    scr = Scrobbler(network)
    signal.signal(signal.SIGTERM, scr.stop)
    signal.signal(signal.SIGINT, scr.stop)
    scr.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
