# mac-scrobbler

A tiny background daemon that watches **Music.app** on macOS and scrobbles what
you play to **[Last.fm](https://www.last.fm)** through the official API.

It's a drop-in replacement for Last.fm's official desktop Scrobbler, which is a
pain to run on recent macOS because of Gatekeeper. This is ~250 lines of Python,
no app bundle, no code signing — just a script that `launchd` keeps alive.

```
Music.app ──(JXA / osascript)──▶ polling loop ──▶ state machine ──▶ pylast ──▶ Last.fm API
```

## What it does

- Detects the track playing in **Music.app** (Apple Music desktop app) and its
  play/pause state.
- Sends **"now playing"** when a track starts.
- Sends the **scrobble** once the track qualifies under Last.fm's
  [Scrobbling 2.0](https://www.last.fm/api/scrobbling) rules (see below).
- Persists the Last.fm session so you authenticate only once.
- Runs unattended in the background, starting at login.

### What it does *not* do

- **Only Music.app.** It does not see YouTube, Spotify, VLC, browsers, or the
  Podcasts app. Anything playing outside Music.app is ignored.
- No GUI / menu-bar item.
- No persistent offline queue yet — a failed scrobble is retried on the next
  poll, but if you quit the process with a scrobble still pending, it's lost.
  (Both are on the [roadmap](#roadmap).)

## Requirements

- macOS with **Music.app** (developed and tested on macOS 26).
- **Python 3.9+** (the macOS Command Line Tools `python3` is fine).
- A free **Last.fm API account**: <https://www.last.fm/api/account/create>

---

## Installation

### 1. Get the code and install dependencies

```bash
git clone <repo-url>   # the "Code" button on the GitHub page has it
cd mac-scrobbler
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Create a Last.fm API account

Go to <https://www.last.fm/api/account/create> and fill in:

| Field | Value |
|---|---|
| Contact email | your email |
| Application name | anything, e.g. `mac scrobbler` (this name shows on the auth screen) |
| Application description | anything |
| Callback URL | **leave empty** (not used for desktop auth) |
| Application homepage | leave empty |

On submit you get an **API key** and a **shared secret**.

### 3. Store your credentials

Create `~/.config/mac-scrobbler/config.json`:

```bash
mkdir -p ~/.config/mac-scrobbler
cat > ~/.config/mac-scrobbler/config.json <<'EOF'
{ "api_key": "YOUR_API_KEY", "api_secret": "YOUR_SHARED_SECRET" }
EOF
chmod 600 ~/.config/mac-scrobbler/config.json
```

> Alternatively, export `LASTFM_API_KEY` and `LASTFM_API_SECRET` in your
> environment instead of using the file.

### 4. Authenticate with Last.fm (one time)

```bash
.venv/bin/python lastfm_auth.py
```

This opens a Last.fm page in your browser. Click **"Yes, allow access"**, then
return to the terminal and press **Enter**. The script exchanges the token for a
**non-expiring session key** and writes it to
`~/.config/mac-scrobbler/session_key` (mode `600`). You won't need to do this
again.

---

## Usage

### Run in the foreground (to test)

```bash
.venv/bin/python scrobbler.py
```

It prints every now-playing and scrobble. Play something in Music.app and watch.
In another terminal you can follow the log:

```bash
tail -f ~/.config/mac-scrobbler/scrobbler.log
```

Then confirm the plays appear at `https://www.last.fm/user/YOUR_USERNAME`.

**Stop it:** `Ctrl+C` (it shuts down cleanly at the end of the current cycle).

The first run may trigger a macOS prompt asking to let the process control
Music.app — **approve it**, otherwise it can't read what's playing.

### Run in the background at login (launchd)

`install-agent.sh` generates `~/Library/LaunchAgents/mac-scrobbler.plist` from
`mac-scrobbler.plist.template` — substituting this checkout's path and your home
directory — lints it, and loads it. Run it from wherever you cloned the repo:

```bash
./install-agent.sh
```

| Task | Command |
|---|---|
| Check it's running | `launchctl list \| grep mac-scrobbler` (a PID on the left = alive) |
| Stop until next login | `launchctl unload ~/Library/LaunchAgents/mac-scrobbler.plist` |
| Restart after editing code | `launchctl unload ~/Library/LaunchAgents/mac-scrobbler.plist && launchctl load -w ~/Library/LaunchAgents/mac-scrobbler.plist` (or just `./install-agent.sh` again) |
| Uninstall for good | `./uninstall-agent.sh` |

`RunAtLoad` starts it at login; `KeepAlive` (`SuccessfulExit=false`) restarts it
if it crashes, throttled to once every 30 s. `launchd` stdout/stderr go to
`~/.config/mac-scrobbler/launchd.{out,err}.log`. The generated plist lives only
on your machine and is not tracked by git.

---

## How it decides to scrobble

The loop polls Music.app every **`POLL_INTERVAL` seconds** (default **10**;
override with the `MAC_SCROBBLER_POLL_INTERVAL` env var).

**Listened time** is accumulated from the change in Music.app's `playerPosition`
between polls — not from a wall clock. So paused time doesn't count, a forward
seek can't over-credit (there's a per-cycle cap), and a jump backwards of more
than 10 s is treated as restarting the track.

| Event | When |
|---|---|
| `update_now_playing` | when a new track starts; refreshed every **120 s** on long tracks until the scrobble fires |
| `scrobble` (permanent, counts for charts) | **once per play**, when *both* Last.fm conditions hold |

**Last.fm's two conditions:**

1. the track is **longer than 30 seconds**, and
2. you've listened to **at least half its length, or 4 minutes — whichever comes first**.

Examples: a 3:00 track scrobbles at 1:30; a 12:00 track scrobbles at 4:00; a 0:25
track never scrobbles (but still sends now-playing).

The scrobble is timestamped with when the track **started**, not when the
threshold was reached. On network/API errors the scrobble is retried on the next
poll (now-playing is not retried).

---

## Project layout

| File | Purpose |
|---|---|
| `scrobbler.py` | main loop + state machine |
| `music_app.py` | `get_current_track()` — reads Music.app via JXA, returns a `Track` |
| `lastfm_auth.py` | one-time Last.fm session-key setup |
| `config.py` | loads credentials / session key / tuning constants |
| `mac-scrobbler.plist.template` | LaunchAgent template (paths filled in by `install-agent.sh`) |
| `install-agent.sh` / `uninstall-agent.sh` | install / remove the launchd agent |
| `requirements.txt` | just `pylast` |

Everything the daemon writes lives in `~/.config/mac-scrobbler/`:
`config.json`, `session_key`, `scrobbler.log`, `launchd.*.log`.

### Implementation notes

- **Why JXA and not AppleScript?** AppleScript coerces numbers to strings using
  the system locale (here the decimal separator is a comma → `254,067`), which is
  fragile to parse. `osascript -l JavaScript` returns clean JSON.
- Tested against **pylast 5.5.0**. pylast 7.x needs a newer Python than the
  system 3.9, so `requirements.txt` pins `pylast>=5.5,<6`.
- Track identity uses Music.app's `persistentID` when available, falling back to
  `artist␟title␟album`.

## Roadmap

- Persistent offline retry queue (survive restarts / long outages).
- Support for Spotify and other players.
- Optional menu-bar UI.

## License

MIT — see [LICENSE](LICENSE).
