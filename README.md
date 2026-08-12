# raspi_watch — TI viewing setup

Watch all four concurrent TI streams at once, with a live scoreboard that does
**not** spoil fights before you see them.

Two independent halves that share no state:

| Half | Runs on | Shows |
|---|---|---|
| **Wall** (`wall/`) | the Mac → TV/projector | four streams tiled 2x2, instant audio switching |
| **Scoreboard** (`scoreboard/`) | this Windows box → small table screen | live scores for every game, held behind the broadcast |

TI 2026 group stage: **Aug 13–16**. Main event: **Aug 20–23**.

---

## The one thing to understand

Valve's API is **live**. The broadcast is **2–5 minutes behind it**. Render the API
directly and the scoreboard tells you about a teamfight before you watch it.

So the scoreboard buffers every poll and shows you the state from `N` seconds ago.
`N` is adjustable from the page — tune it during the first game until a kill on
screen and the tile ticking over happen together, then leave it alone.

---

## Wall (on the Mac)

### One-time setup

```sh
brew install mpv yt-dlp streamlink
```

Already installed and verified: mpv 0.41.0, yt-dlp 2026.07.04, streamlink 8.5.0.

### The four streams

Valve's 2026-08-11 announcement named them, and the Twitch names hold for the
whole event, so `wall/streams.toml` already has the real ones:
`dota2ti`, `dota2ti_2`, `dota2ti_3`, `dota2ti_4` (English; `_cn`, `_ru`, `_es`
variants follow the same A/B/C/D pattern). Nothing to do each morning.

### Only if you use YouTube instead

YouTube gets a single `youtube.com/dota2` link for all four, and each concurrent
stream is its own video ID that **changes daily**. The `@channel/live` URL only
ever resolves to one of them, so each morning:

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
- Fans too loud? Measured on 2026-08-11: four tiles hold the Mac at a 29–41%
  `CPU_Speed_Limit`, and **720p does not help** — same floor, it just takes ~4
  minutes to get there instead of under 1. It runs fine throttled (0 respawns,
  0 dropped frames over 47 minutes). If you change quality anyway, Twitch tiles
  read `quality` and YouTube tiles read `ytdl_format`; the shipped config is
  Twitch.
- YouTube tiles pass `--ytdl-raw-options=no-live-from-start=` so they open at
  the live edge. The opposite spelling makes yt-dlp build an EDL of DVR
  segments that mpv cannot open, and every tile dies ~4s in and respawns
  forever.
- macOS **display mirroring** collapses the panel and the TV into a single
  screen, so `--screen=1` stops existing. The wall detects this and falls back
  to `--screen=0`; use Extended Display to drive the TV on its own.

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

Run it:

```powershell
python -m scoreboard.server
```

Open <http://localhost:8000> on the table screen. It binds `0.0.0.0`, so a phone
on the same network works too — and different viewers can run different delays,
since the delay is a client-side setting.

### On screen

- `−15s` / `+15s` adjust the delay (persisted in the browser)
- `Drafts` toggles hero portraits — off by default, since 40 icons is too dense
  on a small screen
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
2. Sustained four-stream CPU/thermals on the Mac — soaked for 47 minutes on
   2026-08-11 against YouTube live streams (see `MAC_START_HERE.md`). Still
   unverified against the real Twitch streams, which take a different code
   path through streamlink.

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
