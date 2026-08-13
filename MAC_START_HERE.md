# Read this first — what this Mac does during TI 2026

You are on `macbook-pro` (Intel i9-9880H, macOS 15.7.7), user `sachleensingh`.
This directory is `~/raspi_watch`, a git clone of
<https://github.com/chessleensingh/raspi_watch> (public). Update it with
`git -C ~/raspi_watch pull`.

TI 2026 group stage: **Aug 13–16, 2026**. Main event: **Aug 20–23**, Grand
Finals Sunday Aug 23.

## The Mac's job, in full

**Play one stream on the TV/projector, started by hand, and leave it there.**

That's it. Open the main TI stream in whatever player you like, set the volume,
walk away. Nothing on the Windows box reaches into this machine, and nothing
here needs to be running for the rest of the setup to work.

The Windows box does the switching now: a scoreboard on a small screen, and a
viewer on its main screen that changes game when you tap one. It has no
dependency on this Mac at all.

If you are an agent that was sent here to make the wall work: **you probably
weren't**. Check what you were actually asked for before running anything below.

---

## Optional: the 2x2 wall

`wall/wall.py` tiles four streams on this Mac with instant audio switching. It
is no longer part of the setup — it's kept as the fallback if the four-up wall
is wanted on the projector instead of a single stream. Nothing drives it
remotely any more; the HTTP control server it starts on port 8777 has no client.

```sh
cd ~/raspi_watch && /usr/local/bin/python3.12 wall/wall.py
```

Keys: `1`–`4` move audio (instant), `5` fullscreen, `r` respawn dead tiles,
`q` quit. Flags: `--list-displays`, `--dry-run`, `--screen 1`, `--no-control`.

The streams come from `wall/streams.toml` — the same file the Windows viewer
reads, so if the Windows box has been keeping it current, it is already right.

### Ground rules for this machine

Each of these costs a debugging cycle if you don't know it up front:

1. **Use `/usr/local/bin/python3.12`.** The default `python3` is 3.7 (Xcode CLT)
   and has no `tomllib`. `/usr/local/bin/python3` is a *different* 3.7.6 install,
   also wrong.
2. **`scp`/`rsync`/`sftp` into this machine are broken.** A "Biostar command
   logging" banner prints from the shell rc on non-interactive sessions and
   corrupts their protocol. Don't suggest them as a fix if a transfer fails.
3. **`timeout` does not exist** on macOS. Use `gtimeout` (coreutils).
4. **The wall needs a real desktop session and a real terminal.** mpv windows
   won't attach to the TV correctly if spawned from a plain non-interactive
   `ssh host command`, and the hotkeys need a tty. Run it from Terminal.app, or
   `ssh -t`.
5. **This Mac mirrors its displays by default**, which collapses the panel and
   the TV into one screen — mpv then has no `--screen=1` at all. The wall
   detects this and uses `--screen=0` (which *is* the TV, since the TV is the
   mirror master), but the laptop panel shows the same thing. For the TV alone,
   System Settings → Displays → use as **Extended Display**.
6. **pytest for 3.12 lives in the user site.** Homebrew's python is
   externally-managed, so it was installed with
   `python3.12 -m pip install --user --break-system-packages pytest flask requests`.

### Verified working (2026-08-11, don't re-verify)

- `mpv` 0.41.0, `yt-dlp` 2026.07.04, `streamlink` 8.5.0 — all installed
- VideoToolbox hardware decode of a YouTube live stream
- mpv JSON IPC over a unix socket — what makes audio switching instant
- Display detection picks the external **S2-TEK TV (1920x1080)** over the
  built-in Retina panel (1440x900 logical)
- A full dress rehearsal with four YouTube live streams: clean 2x2, audio
  switching over IPC, fullscreen toggle without a reload, clean exit

### If something breaks

- **A tile dies** — press `r`. The wall respawns just that tile.
- **Tiles land on the wrong screen** — `--list-displays`, then set
  `[screen] index` in `streams.toml`.
- **Nothing plays at all** — run `--dry-run`, take the printed mpv command for
  one tile, and run it by hand. That isolates yt-dlp vs mpv vs process
  management.
- **Every tile dies and respawns in a loop, a few seconds apart** — check what
  `--ytdl-raw-options` the dry run prints. It must be `no-live-from-start=`.
  The opposite makes yt-dlp hand mpv an EDL of DVR segments it cannot open, and
  the tile exits about four seconds in, forever.

### Checking the wall without looking at the TV

Terminal has no Screen Recording permission here, so `screencapture` returns the
wallpaper only. Ask mpv instead, over the same IPC sockets the wall uses:

```sh
printf '{"command":["get_property","display-names"]}\n' | nc -U /tmp/ti_wall_0.sock
```

`display-names` proves which physical screen a tile is on, `osd-dimensions`
gives its size, `vo-configured` says the window really exists, and
`playback-time` sampled twice proves frames are moving.

### Thermals, measured 2026-08-11

Four tiles pin this machine's thermal limit, and **lowering the resolution does
not help**. Both runs used four YouTube live streams and `pmset -g therm`:

| | 1080p60, 32 min | 720p60, 15 min (cold start) |
|---|---|---|
| Time to first throttle | under 1 min | ~4 min |
| Steady `CPU_Speed_Limit` | 29–41% | 29–37% |
| CPU mean (all 4 procs) | 76% of one core | 64% of one core |
| Tile respawns | 0 | 0 |

Same floor at both resolutions, which points at package power from four 60fps
windows compositing rather than at decode cost. **It works fine while
throttled**: zero respawns and zero dropped frames across 47 minutes. A
fan-noise question, not a will-it-run question. Untested idea if it becomes a
real problem: cap frame rate (`fps<=?30`) or run three tiles instead of four.

One reason this matters less now: a single manually-played stream costs a
fraction of this, so the default setup runs the Mac cool.

### Design constraint worth preserving

The point of doing the wall natively rather than using multitwitch.tv is that
audio switching is a property change on an already-running player, so it is
instantaneous. If you refactor, do not replace the IPC mechanism with anything
that restarts a stream to change which one is audible. The Windows viewer solves
the same problem the same way, by keeping every stream playing and only changing
which is visible and unmuted.

## Source of truth

<https://github.com/chessleensingh/raspi_watch> — public, so `git pull` works
here with no authentication. (Pushing would still need credentials; this
machine's `gh` token is expired. Read-only is all you need.)
