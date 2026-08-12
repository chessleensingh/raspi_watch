# Read this first — instructions for the agent on the Mac

You are on `macbook-pro` (Intel i9-9880H, macOS 15.7.7), user `sachleensingh`.
This directory is `~/raspi_watch`, a git clone of
<https://github.com/chessleensingh/raspi_watch> (public). Update it with
`git -C ~/raspi_watch pull`.

Your job is the **video wall** half of a two-part TI 2026 viewing setup. The
scoreboard half runs on a separate Windows machine and needs nothing from you.

TI 2026 group stage: **Aug 13–16, 2026**. Main event: **Aug 20–23**, Grand
Finals Sunday Aug 23.

## Ground rules for this machine

These will each cost you a debugging cycle if you don't know them up front:

1. **Use `/usr/local/bin/python3.12`.** The default `python3` is 3.7 (Xcode CLT)
   and has no `tomllib`. `/usr/local/bin/python3` is a *different* 3.7.6 install,
   also wrong.
2. **`scp`/`rsync`/`sftp` into this machine are broken.** A "Biostar command
   logging" banner prints from the shell rc on non-interactive sessions and
   corrupts their protocol. Not your problem locally, but don't suggest them as a
   fix if a transfer fails.
3. **`timeout` does not exist** on macOS. Use `gtimeout` (coreutils) or rely on
   the command's own exit conditions.
4. **The wall needs a real desktop session and a real terminal.** mpv windows
   won't attach to the TV correctly if spawned from a plain non-interactive
   `ssh host command`, and the hotkeys need a tty. Run it from Terminal.app on
   the Mac, or `ssh -t`.
5. **This Mac is currently mirroring its displays**, which collapses the panel
   and the TV into one screen — mpv then has no `--screen=1` at all, and says
   `Screen ID 1 does not exist, falling back to current device`. The wall
   detects this and uses `--screen=0` (which *is* the TV, since the TV is the
   mirror master), but the laptop panel shows the same thing. For the TV alone,
   System Settings → Displays → use as **Extended Display**.
6. **pytest for 3.12 lives in the user site.** Homebrew's python is
   externally-managed, so it was installed with
   `python3.12 -m pip install --user --break-system-packages pytest flask requests`.
   `flask`/`requests` are only there so `tests/test_server.py` can be collected;
   the scoreboard itself never runs here.

## Verified working already

Don't re-verify these; they were tested end to end on 2026-08-11:

- `mpv` 0.41.0, `yt-dlp` 2026.07.04, `streamlink` 8.5.0 — all installed
- VideoToolbox hardware decode of a YouTube live stream (`[vd] Looking at hwdec
  h264-videotoolbox`, frames decoded)
- mpv JSON IPC over a unix socket (`{"request_id":0,"error":"success"}`) — this
  is what makes audio switching instant rather than a stream reload
- Display detection picks the external **S2-TEK TV (1920x1080)** over the
  built-in Retina panel (1440x900 logical). With mirroring on it correctly
  reports `--screen=0`; with mirroring off it picks `--screen=1`.
- A full dress rehearsal on 2026-08-11 with four arbitrary YouTube live
  streams: four tiles in a clean 2x2, audio switching over IPC, fullscreen
  toggle without a reload, clean exit with no orphaned processes.

## What actually needs doing, each morning of the event

**Nothing, most likely.** Valve's 2026-08-11 announcement named the four English
streams, and the Twitch names are stable for the whole event, so
`wall/streams.toml` is already filled in with the real thing:

| Tile | Twitch channel |
|---|---|
| 1 | `dota2ti` (Stream A) |
| 2 | `dota2ti_2` (Stream B) |
| 3 | `dota2ti_3` (Stream C) |
| 4 | `dota2ti_4` (Stream D) |

Chinese, Russian and Spanish use the same A/B/C/D pattern with a language
infix — the full list is in the comments of `streams.toml`.

The daily hunt is only needed **if you switch the wall to YouTube**, where Valve
publishes a single `youtube.com/dota2` link and the four concurrent streams are
four video IDs on that one channel that change every day:

```sh
cd ~/raspi_watch
/usr/local/bin/python3.12 wall/find_streams.py            # official Dota 2 channel
/usr/local/bin/python3.12 wall/find_streams.py --twitch   # probe the Twitch names
```

It prints a ready-to-paste `streams = [...]` block. Put it in `wall/streams.toml`
(the one next to `wall.py` — it is read relative to that file, not to your cwd).

Run it from a Terminal on the Mac:

```sh
cd ~/raspi_watch && /usr/local/bin/python3.12 wall/wall.py
```

Keys: `1`–`4` move audio (instant), `5` fullscreen, `r` respawn dead tiles,
`q` quit.

Useful:

```sh
/usr/local/bin/python3.12 wall/wall.py --list-displays  # which display is which
/usr/local/bin/python3.12 wall/wall.py --dry-run        # print commands, spawn nothing
/usr/local/bin/python3.12 wall/wall.py --screen 1       # force the TV
```

## If something breaks mid-event

- **A tile dies** — press `r`. Streams do drop; the wall respawns just that tile
  rather than tearing everything down.
- **Fans get loud** — expected, and **dropping to 720p does not fix it**. See
  the measurements below. If you do want to change quality anyway, mind which
  knob: the wall is configured for **Twitch**, so the one that matters is
  `quality` (put `720p60,720p,best` first). `ytdl_format` only affects YouTube
  entries and does nothing for a Twitch tile.
- **Tiles land on the wrong screen** — `--list-displays`, then set
  `[screen] index` in `streams.toml`.
- **Nothing plays at all** — run `--dry-run`, take the printed mpv command for
  one tile, and run it by hand. That isolates whether it's yt-dlp, mpv, or the
  wall's process management.
- **Every tile dies and respawns in a loop, a few seconds apart** — check what
  `--ytdl-raw-options` the dry run prints. It must be `no-live-from-start=`.
  The opposite (`live-from-start=`) makes yt-dlp hand mpv an EDL of DVR
  segments it cannot open: `EDL: Could not open source file ...` then `No video
  or audio streams selected`, and the tile exits about four seconds in, forever.
  This was the state of the repo until 2026-08-11.

## Checking the wall without looking at the TV

Terminal has no Screen Recording permission on this machine, so `screencapture`
returns the wallpaper only and the CoreGraphics window list hides real window
frames. Ask mpv instead — it answers over the same IPC sockets the wall uses:

```sh
printf '{"command":["get_property","display-names"]}\n' | nc -U /tmp/ti_wall_0.sock
```

`display-names` proves which physical screen a tile is on, `osd-dimensions`
gives its size, `vo-configured` says the window really exists, and
`playback-time` sampled twice proves frames are moving.

## Thermals, measured 2026-08-11

Four tiles pin this machine's thermal limit, and **lowering the resolution does
not help**. Both runs used four YouTube live streams and `pmset -g therm`:

| | 1080p60, 32 min | 720p60, 15 min (cold start) |
|---|---|---|
| Time to first throttle | under 1 min | ~4 min |
| Steady `CPU_Speed_Limit` | 29–41% | 29–37% |
| CPU mean (all 4 procs) | 76% of one core | 64% of one core |
| Tile respawns | 0 | 0 |

Idle recovers to 100% within about 40 seconds of quitting, so the wall is
what's causing it. Same floor at both resolutions, which points at package
power from four 60fps windows compositing rather than at decode cost — the CPU
cores are nearly idle throughout (76% of *one* core out of 1600% available) and
both resolutions decode in hardware via VideoToolbox.

**It works fine while throttled**: zero respawns and zero dropped frames across
47 minutes of soaking. So this is a fan-noise and heat question for a four-day
event, not a will-it-run question. Untested idea if it becomes a real problem:
cap frame rate (`fps<=?30`) or run three tiles instead of four, both of which
cut compositing work more directly than resolution does.

Caveat: all of this used YouTube streams, because the Twitch channels don't go
live until Aug 13. The shipped config is Twitch, which runs through streamlink
instead of mpv-driving-yt-dlp. Treat these as a good proxy, not the real thing.

## Remote control from the scoreboard

`wall.py` starts a small HTTP server on port 8777 exposing `GET /status`,
`POST /audio/<tile>` and `POST /fullscreen`, so the scoreboard on the Windows
box can switch which stream has audio when a game is tapped. Disable with
`--no-control`.

**The macOS Application Firewall blocks it.** The firewall is enabled on this
machine and only `/usr/bin/python3` is on its allow list, so inbound connections
to `python3.12` are accepted and then instantly dropped — the Mac logs
`OSError: [Errno 57] Socket is not connected` and the client sees a reset. This
looks like a bug in the code and is not.

Two fixes, in order of preference:

1. **The Windows side runs an SSH tunnel** (`scripts/wall_tunnel.ps1`), which
   forwards to `127.0.0.1` on this Mac and sidesteps the firewall entirely. This
   is already how it is configured, and it leaves no port exposed.
2. Allow the binary once:
   ```sh
   sudo /usr/libexec/ApplicationFirewall/socketfilterfw \
        --add /usr/local/bin/python3.12 --unblockapp /usr/local/bin/python3.12
   ```

If you run `wall.py` from Terminal.app rather than over ssh, macOS may instead
show a GUI prompt asking whether to accept incoming connections. Allowing it
there has the same effect as option 2.

## Design constraint worth preserving

The whole point of doing this natively rather than using multitwitch.tv is that
audio switching is a property change on an already-running player, so it is
instantaneous. If you refactor, do not replace the IPC mechanism with anything
that restarts a stream to change which one is audible.

## Source of truth

<https://github.com/chessleensingh/raspi_watch> — public, so `git pull` works
here with no authentication. (Pushing would still need credentials; this
machine's `gh` token is expired. Read-only is all you need.)
