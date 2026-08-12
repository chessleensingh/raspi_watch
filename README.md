# raspi_watch — TI viewing setup

Watch all four concurrent TI streams at once, with a live scoreboard that does
**not** spoil fights before you see them.

Two independent halves that share no state:

| Half | Runs on | Shows |
|---|---|---|
| **Wall** (`wall/`) | the Mac → TV/projector | four streams tiled 2x2, instant audio switching |
| **Scoreboard** (`scoreboard/`) | this Windows box → small table screen | live scores for every game, held behind the broadcast |

TI 2026 group stage: **Aug 13–16**.

---

## The one thing to understand

Valve's API is **live**. The broadcast is **2–5 minutes behind it**. Render the API
directly and the scoreboard tells you about a teamfight before you watch it.

So the scoreboard buffers every poll and shows you the state from `N` seconds ago.

**`N` is set automatically.** Valve reports the broadcast delay per game in
`stream_delay_s`, and the page adopts it — the readout says "from Valve" when it
does. Observed values in the wild are 10, 120 and 300 seconds, so guessing a
fixed number would have been wrong most of the time. Where several games
disagree, the largest wins: showing data older than necessary is harmless,
showing it too early is the one thing this exists to prevent.

The `−15s` / `+15s` buttons still override it, and your choice is remembered.
If the broadcast you're watching adds its own delay on top of Valve's, nudge it
until a kill on screen and the tile ticking over happen together.

---

## Wall (on the Mac)

### One-time setup

```sh
brew install mpv yt-dlp streamlink
```

Already installed and verified: mpv 0.41.0, yt-dlp 2026.07.04, streamlink 8.5.0.

### Every day of the event

YouTube gives each concurrent stream its own video ID, and **those IDs change
daily**. The `@channel/live` URL only ever resolves to one of them, so each
morning:

```sh
ssh mac-ti
cd ~/raspi_watch
/usr/local/bin/python3.12 wall/find_streams.py          # official Dota 2 channel
/usr/local/bin/python3.12 wall/find_streams.py --twitch # or probe Twitch names
```

It prints a ready-to-paste `streams = [...]` block. Put it in `wall/streams.toml`,
then push and run:

```powershell
.\scripts\sync_to_mac.ps1
```

```sh
# in a Terminal ON THE MAC (hotkeys need a real terminal, and the windows need
# a real desktop session — a plain non-interactive ssh command won't do)
cd ~/raspi_watch && /usr/local/bin/python3.12 wall/wall.py
```

### Keys

| Key | Does |
|---|---|
| `1`–`4` | move audio to that tile — instant, no reload |
| `5` | fullscreen the tile that has audio |
| `r` | respawn any dead tiles |
| `q` | quit, killing every child process |

### Useful flags

```sh
python3.12 wall.py --list-displays   # which display is which
python3.12 wall.py --dry-run         # print commands and geometry, spawn nothing
python3.12 wall.py --screen 1        # force a display
```

### Notes

- **Use `/usr/local/bin/python3.12`.** The Mac's default `python3` is 3.7, which
  has no `tomllib`.
- Display auto-detection prefers an **external** display over the MacBook's own
  panel. Retina panels are converted to logical points — using their advertised
  pixel count puts three of the four tiles off-screen.
- YouTube entries go straight to mpv (which drives yt-dlp). Twitch entries go via
  streamlink, which handles ads and low-latency mode far better. You can mix both
  in one wall.
- Fans too loud? Lower `ytdl_format` from `height<=?1080` to `720`.

---

## Scoreboard (on this box)

```powershell
pip install -r requirements.txt
```

Put a free key from <https://steamcommunity.com/dev/apikey> into `config.toml`,
or set `STEAM_API_KEY` in the environment (which wins over the file).

Find TI's league id once it's live, and paste it into `config.toml`:

```powershell
python scripts\find_league.py
```

Run it and put it on the second screen in one step:

```powershell
.\scripts\open_scoreboard.ps1
```

That starts the server and opens the page fullscreen on the secondary display
(falling back to the primary if there's only one). Use `-NoServer` if the server
is already running. Fullscreen matters: in a normal window the taskbar clips the
bottom row of tiles.

To run the server alone:

```powershell
python -m scoreboard.server
```

It binds `0.0.0.0`, so a phone on the same network works too — and different
viewers can run different delays, since the delay is a per-client setting.

### Layout

Tiles are laid out by game count: 1 game fills the screen, 2–4 go in a 2x2,
more spill into three columns. Four is the TI group-stage case and is what the
sizing is tuned for. Verified on a 1440x900 secondary display.

### On screen

- `−15s` / `+15s` adjust the delay (persisted in the browser)
- `Drafts` toggles hero portraits — off by default, since 40 icons is too dense
  on a small screen
- `↻ Refresh` clears this browser's saved delay and draft settings and reloads
  bypassing the cache. Use it if the delay looks wrong (it's remembered across
  sessions, so an old value can linger) or the page has been open for days
- The status line says `warming up` while there's less than `N` seconds of
  history, and `STALE` if Valve's API stops responding. It never silently shows
  fresher data than you asked for, and never blanks a tile — the last good
  snapshot stays up.

---

## Tests

```powershell
python -m pytest tests/ -q     # 67 tests, no network needed
```

Everything is tested against a recorded fixture, including the cases that
actually break parsers during a real tournament: a game mid-draft with no
`scoreboard` key, and a team with no registered name.

The two things tests can't cover, both needing the live event:

1. Dialling the delay to match the broadcast.
2. Sustained four-stream CPU/thermals on the Mac — watch it through one full
   game before trusting it for a four-day event.

---

## Layout

```
scoreboard/
  delay.py       the spoiler guard — time-indexed snapshot buffer
  models.py      normalizes Valve's payload; the seam for an OpenDota fallback
  source.py      Valve Web API client
  heroes.py      hero_id -> name/icon, cached to disk
  server.py      Flask app + background poller
  static/        the page (no build step, no framework)
wall/
  wall.py        tiling, spawning, IPC audio switching
  find_streams.py  daily stream discovery
  streams.toml   the four streams + display choice
scripts/
  find_league.py     discover TI's league id
  sync_to_mac.ps1    push the wall to the Mac
```

## Why the Pi isn't in this

A Pi 3B has 1GB of RAM and one VideoCore IV decode path — about one 480–720p
stream, never four. The scoreboard is deliberately a plain web app with no build
step and no framework, so it can move to the Pi later (silent, always-on) with no
code changes. That's why the project keeps the name.
