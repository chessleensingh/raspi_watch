# Windows viewer: click a game, watch it on the main screen

**Date:** 2026-08-12
**Status:** approved, ready for implementation planning

## The change

Today the scoreboard on the small screen reaches across the network to the Mac
and moves the audio of a 2x2 video wall. That coupling — an SSH tunnel, a
control server inside `wall.py`, and a macOS firewall workaround — exists only
to make one machine drive another.

It goes away. The Mac becomes fully isolated: one permanent stream, started and
volume-set by hand, with nothing in this repo touching it. Clicking a game on
the small screen instead drives a **new fullscreen viewer on the Windows main
screen**, which swaps to that game's stream instantly.

```
Mac / projector    [ main stream, manual, never changes, repo does not touch it ]

Windows main       +--------------------------------+
                   |   stream for the clicked game  |   <- new: /viewer
                   |          (fullscreen)          |
                   +--------------------------------+

Windows small      [ scoreboard ]  <- click a game
```

## Goals

- Clicking a game on the small screen switches the main screen to that game.
- The switch is instant — no re-buffering.
- Nothing in the repo connects to the Mac.

## Non-goals

- Controlling the Mac in any form. `wall/wall.py` stays on disk as the fallback
  for a 2x2 wall, but nothing is wired to it.
- Changing the delay buffer. `scoreboard/delay.py` is the reason this project
  exists and is untouched here.

## Architecture

Three pieces, all on the Windows box, all served by the existing Flask app:

| Piece | Where | Role |
|---|---|---|
| Scoreboard | small screen, `/` | Existing page. Clicking a game POSTs a selection. |
| Selection state | Flask, in memory | One integer: which stream is selected. |
| Viewer | main screen, `/viewer` | Four preloaded players; shows and unmutes the selected one. |

### Why the selection lives on the server

`server.py`'s docstring states that the delay is a per-request parameter so the
server stays stateless. The selection breaks that rule deliberately, and the
docstring must be amended to say why: the delay is *per-client by design* (the
table screen and a phone may legitimately run different delays), whereas the
selection is *inherently one shared value* passing between two browsers on two
screens. There is nowhere else for it to live.

State is a single integer held in `app.config`, which the viewer compares
against what it is currently showing. Assigning it needs no lock: it is one
atomic rebind, and a lost race would at worst cost one 500ms poll. It is not
persisted — a server restart resets to "nothing selected", and the viewer shows
stream 0 until the first click.

### Data flow

```
small screen                     Flask                      main screen
    |                              |                             |
    | POST /api/viewer/select/2    |                             |
    |----------------------------->| selected = 2                |
    |         {"selected": 2}      |                             |
    |<-----------------------------|                             |
    |                              |    GET /api/viewer (500ms)  |
    |                              |<----------------------------|
    |                              |  {"selected": 2, ...}       |
    |                              |---------------------------->|
    |                              |                     raise + unmute player 2
```

500ms polling, not SSE. The app is otherwise entirely polling-based, the payload
is a few bytes over localhost, and the switch itself is instant because the
player is already buffered — SSE would buy at most half a second at the cost of
a streaming endpoint in an app that has none.

## Components

### `scoreboard/streams.py` (new)

Reads `wall/streams.toml` — the same file `wall.py` uses, so there is one stream
list — and resolves each entry to a browser-embeddable descriptor.

```python
@dataclass(frozen=True)
class Stream:
    index: int
    kind: str      # "youtube" | "twitch" | "empty"
    id: str        # video id, or twitch channel name
    label: str     # for the viewer's corner badge
```

Resolution rules, following `wall.py`'s existing `is_youtube` convention:

| Entry in `streams.toml` | Result |
|---|---|
| `https://www.youtube.com/watch?v=ID` | `youtube` / `ID` |
| `https://youtu.be/ID` | `youtube` / `ID` |
| `https://www.youtube.com/@dota2/live` | `empty` — **not embeddable**, see below |
| `dota2ti` (bare name) | `twitch` / `dota2ti` |
| `""` | `empty` |

It imports nothing from `wall/` — that module carries macOS-only concerns
(`system_profiler`, mpv sockets). It only reads the TOML file.

**The `@channel/live` gap.** That URL form cannot be embedded; YouTube embeds
need a concrete video ID. `streams.toml` currently holds one `@dota2/live` entry
and three blanks, so it must be filled with real IDs regardless. An `empty`
slot renders as a dark tile reading "no stream configured" rather than failing.

### `/api/viewer` endpoints (in `server.py`)

- `GET /api/viewer` → `{"selected": int|null, "count": int, "streams": [...]}`
  Used by the viewer to poll, and by the scoreboard to learn the stream count
  for its badge cycling.
- `POST /api/viewer/select/<int:index>` → `{"selected": index}`, or `400` if the
  index is out of range.

`/api/games` is untouched by any of this — a broken viewer must never affect the
scores.

### `scoreboard/static/viewer.html` + `viewer.js` (new)

Plain HTML and JS, no build step, matching the scoreboard's existing style.

**Four players, stacked.** All four are created at load, each full-size and
absolutely positioned in one stack. Only the selected one is opaque and on top;
the rest sit behind at `opacity: 0`, still playing, still muted.

Critically they are **not** hidden with `display: none` or unmounted — browsers
throttle or unload rendering for those, which would reintroduce the buffering
delay that preloading exists to avoid. Visibility is `opacity` and `z-index`
only.

**YouTube players** use the IFrame Player API (`https://www.youtube.com/iframe_api`),
because `mute()`/`unMute()` must be callable programmatically — a plain iframe
whose `src` we swap cannot be unmuted without a reload. Loaded with
`autoplay=1&mute=1`.

**Twitch players** (fallback path only) use the Twitch Embed JS API, which
offers the same control. Twitch embeds require a `parent=` matching the page's
hostname; the viewer passes `location.hostname`, so it works at `localhost` and
breaks only if the page is opened under a name Twitch rejects. Documented, not
solved — Twitch is the fallback and YouTube is the configured path.

**Audio.** Browsers require autoplay to be muted, and unmuting requires a user
gesture on the viewer window itself. So all four load muted and the page shows a
one-time "click to unmute" overlay. After that click, audio follows every
selection: the newly selected player unmutes, the previous one mutes. Before it,
the picture switches silently.

**Keys** (on the viewer window): `1`–`4` select directly, `M` toggle mute,
`F` fullscreen.

### `scoreboard/static/app.js` (modified)

`switchWallAudio` becomes `selectStream`, POSTing `/api/viewer/select/<index>`.
`loadWallStatus` becomes `loadViewerStatus`, reading `/api/viewer`.

The game-to-stream mapping carries over **verbatim**: `wallTileFor` /
`setWallTile`, keyed by `match_id` in localStorage, defaulting to screen
position modulo the stream count, with a badge that cycles it on click. Nothing
in Valve's payload connects a match to a stream URL, so the mapping still cannot
be derived and still has to be stated by hand. Names change (`wallMap` →
`streamMap`, `.wall-badge` → `.stream-badge`); behaviour does not.

### `scripts/open_viewer.ps1` (new)

A near-copy of `open_scoreboard.ps1`, differing in two ways: it opens
`/viewer`, and it targets the **primary** display rather than the first
non-primary one. Same Brave-first browser search, same `--app` +
`--start-fullscreen` flags.

## Removals

| Removed | Reason |
|---|---|
| `/api/wall` and `/api/wall/audio/<tile>` in `server.py` | The Mac coupling. |
| `wall_url` in `config.py`, `[wall]` in `config.toml` / `config.example.toml` | Same, plus the comment block documents a macOS firewall workaround that no longer applies to anything and would mislead. |
| `scripts/wall_tunnel.ps1` | Existed solely to reach the Mac. |
| Wall-control tests in `tests/test_server.py` | Cover removed endpoints. |

`wall/wall.py` — including its control server — **stays**, untouched and
unwired. It is the fallback if the 2x2 wall is ever wanted again, and deleting
it would discard working, verified code.

## Operational change

`wall/find_streams.py` resolves the daily YouTube video IDs and currently runs
on the Mac, which needs `yt-dlp`. With the Mac isolated, that morning routine
moves to the Windows box:

```
pip install yt-dlp          # add to requirements.txt
python wall/find_streams.py # paste the four IDs into wall/streams.toml
```

This must be done each morning of the group stage (Aug 13-16), because YouTube's
concurrent TI streams are separate video IDs that change daily. Twitch needs no
`yt-dlp` and its channel names are stable for the whole event, but it injects
unstrippable ads, which is why YouTube is the configured path.

`README.md` and `MAC_START_HERE.md` both need updating: the Mac doc drops to
"play one stream, set the volume, done", and the README's daily routine gains
the viewer and moves `find_streams.py` to Windows.

## Testing

Extending `tests/test_server.py`'s existing pattern (`create_app` with
`start_poller=False` and a fake source):

- `GET /api/viewer` with no selection returns `selected: null` and the stream
  list parsed from `streams.toml`.
- `POST /api/viewer/select/2` sets it; a following `GET` reports `2`.
- An out-of-range index returns `400` and leaves the previous selection intact.
- `/api/games` is unaffected by any selection activity.

New `tests/test_streams.py` covers resolution: each entry form in the table
above maps to the expected `Stream`, blanks and `@channel/live` become `empty`,
and a missing or malformed `streams.toml` yields an empty list rather than
raising — a broken stream config must not stop the scoreboard from starting.

Manual verification, since browser autoplay and player-API behaviour cannot be
unit-tested: with four real streams configured, clicking a game on the small
screen switches the main screen with no visible re-buffer, and audio follows
after the unmute gesture.

## Risks

**Four concurrent 1080p decodes on the Windows box.** This is the same load
`wall.py` put on the Mac, and it is the price of instant switching, accepted
deliberately. If the box struggles, the mitigation is the `ytdl_format` height
cap that already exists for the Mac — or dropping to preloading two streams.

**Streams drift out of sync.** Each player buffers independently, so the four
are not at identical broadcast positions, making the configured delay
approximate across a switch. This is already true of the existing wall and is
inherent to preloading; the delay is tunable live for exactly this reason.
