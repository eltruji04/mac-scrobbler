"""Read the current playback state from Music.app via JXA (osascript -l JavaScript).

JXA is used instead of plain AppleScript because AppleScript coerces numbers to
strings using the system locale (e.g. "254,067" with a decimal comma), which is
awkward to parse reliably. JXA hands back clean JSON.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

_JXA = r"""
function run() {
  var Music = Application("Music");
  if (!Music.running()) return JSON.stringify({state: "stopped"});
  var state = Music.playerState();  // "stopped" | "playing" | "paused" | "fast forwarding" | "rewinding"
  var out = {state: state};
  if (state === "playing" || state === "paused") {
    try {
      var t = Music.currentTrack;
      out.name = t.name();
      out.artist = t.artist();
      out.album = t.album();
      out.albumArtist = t.albumArtist();
      out.duration = t.duration();          // seconds (float)
      out.position = Music.playerPosition(); // seconds (float)
      out.trackNumber = t.trackNumber();
      try { out.persistentID = t.persistentID(); } catch (e) {}
    } catch (e) {
      return JSON.stringify({state: state, error: String(e)});
    }
  }
  return JSON.stringify(out);
}
"""


@dataclass
class Track:
    state: str  # "playing" | "paused" | "stopped"
    name: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    duration: float = 0.0
    position: float = 0.0
    track_number: int = 0
    persistent_id: str = ""

    @property
    def is_active(self) -> bool:
        return self.state in ("playing", "paused")

    @property
    def identity(self) -> str:
        """Stable key for "is this the same track"."""
        if self.persistent_id:
            return self.persistent_id
        return f"{self.artist}␟{self.name}␟{self.album}"


class MusicAppError(RuntimeError):
    pass


def get_current_track(timeout: float = 10.0) -> Track:
    """Return a :class:`Track`. Raises :class:`MusicAppError` on osascript failure."""
    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", _JXA],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover
        raise MusicAppError(f"osascript timed out after {timeout}s") from exc
    except FileNotFoundError as exc:  # pragma: no cover
        raise MusicAppError("osascript not found (not macOS?)") from exc

    if proc.returncode != 0:
        raise MusicAppError(
            f"osascript exited {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
        )

    raw = proc.stdout.strip()
    if not raw:
        raise MusicAppError("empty output from osascript")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MusicAppError(f"could not parse osascript output: {raw!r}") from exc

    if "error" in data:
        raise MusicAppError(f"JXA error: {data['error']}")

    state = data.get("state", "stopped")
    if state not in ("playing", "paused"):
        return Track(state="stopped")

    return Track(
        state=state,
        name=data.get("name", "") or "",
        artist=data.get("artist", "") or "",
        album=data.get("album", "") or "",
        album_artist=data.get("albumArtist", "") or "",
        duration=float(data.get("duration") or 0.0),
        position=float(data.get("position") or 0.0),
        track_number=int(data.get("trackNumber") or 0),
        persistent_id=str(data.get("persistentID") or ""),
    )


if __name__ == "__main__":  # quick manual check
    print(get_current_track())
