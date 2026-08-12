# Read this first — instructions for the agent on the Mac

You are on `macbook-pro` (Intel i9-9880H, macOS 15.7.7), user `sachleensingh`.
This directory is `~/raspi_watch`, a git clone of
<https://github.com/chessleensingh/raspi_watch> (public). Update it with
`git -C ~/raspi_watch pull`.

Your job is the **video wall** half of a two-part TI 2026 viewing setup. The
scoreboard half runs on a separate Windows machine and needs nothing from you.

TI 2026 group stage: **Aug 13–16, 2026**.

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

## Verified working already

Don't re-verify these; they were tested end to end on 2026-08-11:

- `mpv` 0.41.0, `yt-dlp` 2026.07.04, `streamlink` 8.5.0 — all installed
- VideoToolbox hardware decode of a YouTube live stream (`[vd] Looking at hwdec
  h264-videotoolbox`, frames decoded)
- mpv JSON IPC over a unix socket (`{"request_id":0,"error":"success"}`) — this
  is what makes audio switching instant rather than a stream reload
- Display detection picks the external **S2-TEK TV (1920x1080, `--screen=1`)**
  over the built-in Retina panel (`--screen=0`, 1440x900 logical)

## What actually needs doing, each morning of the event

YouTube gives every concurrent stream its own video ID, and **those IDs change
daily**. The `@dota2/live` URL only ever resolves to one of them, so it cannot
fill all four tiles.

```sh
cd ~/raspi_watch
/usr/local/bin/python3.12 wall/find_streams.py            # official Dota 2 channel
/usr/local/bin/python3.12 wall/find_streams.py --twitch   # or probe Twitch names
```

It prints a ready-to-paste `streams = [...]` block. Put it in `wall/streams.toml`
(the one next to `wall.py` — it is read relative to that file, not to your cwd).
As of Aug 11 Valve had **not** published the secondary channel names, so the
current entries are placeholders.

Then run it from a Terminal on the Mac:

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
- **Fans get loud / frames drop** — lower `ytdl_format` in `streams.toml` from
  `height<=?1080` to `height<=?720`. Four 60fps decodes is the expensive case.
- **Tiles land on the wrong screen** — `--list-displays`, then set
  `[screen] index` in `streams.toml`.
- **Nothing plays at all** — run `--dry-run`, take the printed mpv command for
  one tile, and run it by hand. That isolates whether it's yt-dlp, mpv, or the
  wall's process management.

## Design constraint worth preserving

The whole point of doing this natively rather than using multitwitch.tv is that
audio switching is a property change on an already-running player, so it is
instantaneous. If you refactor, do not replace the IPC mechanism with anything
that restarts a stream to change which one is audible.

## Source of truth

<https://github.com/chessleensingh/raspi_watch> — public, so `git pull` works
here with no authentication. (Pushing would still need credentials; this
machine's `gh` token is expired. Read-only is all you need.)
