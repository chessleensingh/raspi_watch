"""Four live streams tiled 2x2, with instant audio switching.

Runs on the Mac. YouTube tiles are an `mpv` window driving yt-dlp directly;
Twitch tiles are `streamlink` feeding one. Either way the window is placed with
--geometry. All four start muted; pressing 1-4 unmutes one and mutes the rest by
writing a single JSON line to that mpv's IPC socket.

That is the whole reason for doing this natively rather than using multitwitch.tv:
switching is a property change on an already-running player, so it is instant and
does not reload the stream.

    python3 wall.py              # run it
    python3 wall.py --dry-run    # print the commands and geometry, spawn nothing

Keys:  1-4 audio   5 fullscreen toggle   r respawn current tile   q quit
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "streams.toml"
# Always POSIX: the wall only ever runs on the Mac. Building this with pathlib
# would render backslashes when the tests run on Windows.
SOCKET_DIR = "/tmp"
SOCKET_PREFIX = "ti_wall"
FALLBACK_SCREEN = (1920, 1080)


# --------------------------------------------------------------------------
# Pure helpers - these are the testable parts.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Geometry:
    width: int
    height: int
    x: int
    y: int

    def as_mpv_arg(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"


def tile_geometry(screen_w: int, screen_h: int, index: int, count: int = 4) -> Geometry:
    """Where tile `index` (0-based) sits in a grid covering the screen.

    Four tiles make a 2x2. Fewer than four still tile sensibly rather than
    leaving the screen mostly empty, since streams do go offline mid-tournament.
    """
    if index < 0 or index >= count:
        raise ValueError(f"tile index {index} out of range for {count} tiles")

    cols = 1 if count == 1 else 2
    rows = -(-count // cols)  # ceiling division

    width = screen_w // cols
    height = screen_h // rows
    return Geometry(
        width=width,
        height=height,
        x=(index % cols) * width,
        y=(index // cols) * height,
    )


def socket_path(index: int) -> str:
    return f"{SOCKET_DIR}/{SOCKET_PREFIX}_{index}.sock"


def is_youtube(entry: str) -> bool:
    return "youtube.com" in entry or "youtu.be" in entry


def mpv_options(geometry: Geometry, index: int, screen_index: int = 0) -> list[str]:
    """mpv flags shared by both pipelines."""
    return [
        # --geometry offsets are relative to the chosen screen, so without this
        # every tile lands on the laptop panel instead of the TV.
        f"--screen={screen_index}",
        f"--fs-screen={screen_index}",
        "--no-border",
        "--force-window=yes",
        "--ontop=no",
        "--keep-open=no",
        "--mute=yes",
        "--no-osc",
        "--cursor-autohide=100",
        f"--geometry={geometry.as_mpv_arg()}",
        f"--autofit={geometry.width}x{geometry.height}",
        f"--title=TI-tile-{index + 1}",
        f"--input-ipc-server={socket_path(index)}",
        # Hardware decode through VideoToolbox. This is what makes four
        # concurrent 1080p streams cheap on an Intel Mac.
        "--hwdec=videotoolbox",
        "--profile=low-latency",
    ]


def build_command(entry: str, quality: str, geometry: Geometry, index: int,
                  mpv_bin: str, streamlink_bin: str,
                  ytdl_format: str = "", screen_index: int = 0) -> list[str]:
    """The command for one tile.

    YouTube goes straight to mpv, which drives yt-dlp internally - no second
    process and no pipe. Twitch goes through streamlink, which handles ad
    interruptions and low-latency mode far better than yt-dlp does.
    """
    options = mpv_options(geometry, index, screen_index)

    if is_youtube(entry):
        cmd = [mpv_bin, entry, *options]
        if ytdl_format:
            cmd.append(f"--ytdl-format={ytdl_format}")
        # Live streams must start at the live edge, not the DVR buffer start.
        # `live-from-start` does the opposite: yt-dlp hands mpv an EDL of DVR
        # segments that mpv cannot open ("No video or audio streams selected"),
        # so every tile dies about four seconds in and respawns forever.
        cmd.append("--ytdl-raw-options=no-live-from-start=")
        return cmd

    target = entry if entry.startswith("http") else f"twitch.tv/{entry}"
    return [
        streamlink_bin,
        "--player", mpv_bin,
        "--player-args", " ".join(["{playerinput}", *options]),
        "--twitch-low-latency",
        # Streams drop mid-tournament; keep trying rather than dying.
        "--retry-streams", "5",
        "--retry-max", "0",
        "--retry-open", "3",
        "--stream-timeout", "60",
        "--loglevel", "warning",
        target,
        quality,
    ]


@dataclass(frozen=True)
class Display:
    name: str
    width: int
    height: int
    retina: bool
    mirrored: bool = False

    @property
    def logical_size(self) -> tuple[int, int]:
        """What mpv's --geometry actually works in.

        Retina panels report physical pixels but are addressed in points at half
        that. Using the physical numbers puts three of the four tiles off-screen.
        """
        return (self.width // 2, self.height // 2) if self.retina else (self.width, self.height)


# The MacBook's own panel. Anything else is an external display.
_BUILTIN_PATTERNS = ("color lcd", "built-in", "liquid retina")


def parse_displays(system_profiler_text: str) -> list[Display]:
    """Parse `system_profiler SPDisplaysDataType` into displays, in listed order."""
    displays = []
    current_name = None

    for line in system_profiler_text.splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and "resolution" not in stripped.lower():
            current_name = stripped.rstrip(":")
            continue

        match = re.search(r"Resolution:\s*(\d+)\s*x\s*(\d+)(.*)", stripped)
        if match:
            displays.append(Display(
                name=current_name or "unknown",
                width=int(match.group(1)),
                height=int(match.group(2)),
                retina="retina" in match.group(3).lower(),
            ))
            continue

        # "Mirror: On" comes after the Resolution line inside the same block,
        # so it lands on the display we most recently appended.
        if displays and re.fullmatch(r"Mirror:\s*On", stripped):
            displays[-1] = replace(displays[-1], mirrored=True)

    return displays


def mirroring_is_on(displays: list[Display]) -> bool:
    """True when macOS is mirroring, which collapses every panel into one screen.

    This matters because mpv indexes real screens: with mirroring on there is
    only ever `--screen=0`, and asking for `--screen=1` gets you
    "Screen ID 1 does not exist, falling back to current device".
    """
    return any(d.mirrored for d in displays)


def choose_display(displays: list[Display]) -> tuple[int, Display] | None:
    """Pick the display to put the wall on: an external one if there is one.

    Preferring "largest" would pick the MacBook's own Retina panel over a 1080p
    TV, which is exactly backwards - the whole point is to watch on the big screen.
    """
    if not displays:
        return None

    for index, display in enumerate(displays):
        if not any(p in display.name.lower() for p in _BUILTIN_PATTERNS):
            return index, display

    return 0, displays[0]


# --------------------------------------------------------------------------
# Runtime
# --------------------------------------------------------------------------

def detect_display() -> tuple[int, tuple[int, int], str]:
    """(screen index, logical size, description) for the display to use."""
    try:
        out = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return 0, FALLBACK_SCREEN, "detection failed, assuming 1920x1080"

    displays = parse_displays(out)
    chosen = choose_display(displays)
    if chosen is None:
        return 0, FALLBACK_SCREEN, "no displays found, assuming 1920x1080"

    index, display = chosen

    # Mirroring collapses every panel into a single screen, so screen 1 does not
    # exist and mpv would silently fall back. The mirror master is what the TV
    # shows, and that is screen 0.
    if mirroring_is_on(displays):
        return 0, display.logical_size, (
            f"{display.name} (mirroring is ON, so there is only one screen; "
            "switch to Extended Display to address the TV on its own)"
        )

    note = " (Retina, using logical points)" if display.retina else ""
    return index, display.logical_size, f"{display.name}{note}"


def mpv_command(index: int, command: list, timeout: float = 1.0) -> bool:
    """Send one JSON command to a tile's mpv. False if it isn't listening yet."""
    path = socket_path(index)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(path)
            sock.sendall(json.dumps({"command": command}).encode() + b"\n")
        return True
    except (OSError, socket.timeout):
        return False


class Wall:
    def __init__(self, streams: list[str], quality: str, screen: tuple[int, int],
                 mpv_bin: str, streamlink_bin: str, ytdl_format: str = "",
                 screen_index: int = 0) -> None:
        self.streams = streams
        self.quality = quality
        self.screen = screen
        self.mpv_bin = mpv_bin
        self.streamlink_bin = streamlink_bin
        self.ytdl_format = ytdl_format
        self.screen_index = screen_index
        self.procs: dict[int, subprocess.Popen] = {}
        self.active = 0

    def command_for(self, index: int) -> list[str]:
        geometry = tile_geometry(*self.screen, index=index, count=len(self.streams))
        return build_command(
            self.streams[index], self.quality, geometry, index,
            self.mpv_bin, self.streamlink_bin, self.ytdl_format, self.screen_index,
        )

    def spawn(self, index: int) -> None:
        stale = Path(socket_path(index))
        if stale.exists():
            stale.unlink(missing_ok=True)

        # Own process group per tile, so terminating a tile also kills the mpv
        # child. An orphaned streamlink keeps pulling bandwidth invisibly.
        self.procs[index] = subprocess.Popen(
            self.command_for(index),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"  tile {index + 1}: {self.label(index)}")

    def label(self, index: int) -> str:
        entry = self.streams[index]
        return entry if entry.startswith("http") else f"twitch.tv/{entry}"

    def kill(self, index: int) -> None:
        proc = self.procs.pop(index, None)
        if not proc or proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
        except (ProcessLookupError, PermissionError):
            pass
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)

    def start_all(self) -> None:
        print(f"Screen {self.screen[0]}x{self.screen[1]}, {len(self.streams)} tiles:")
        for index in range(len(self.streams)):
            self.spawn(index)

    def stop_all(self) -> None:
        for index in list(self.procs):
            self.kill(index)
        for index in range(len(self.streams)):
            Path(socket_path(index)).unlink(missing_ok=True)

    def set_audio(self, index: int) -> None:
        """Unmute one tile, mute the others. Instant - no stream reload."""
        self.active = index
        for i in range(len(self.streams)):
            mpv_command(i, ["set_property", "mute", i != index])
        print(f"audio -> tile {index + 1} ({self.label(index)})")

    def toggle_fullscreen(self) -> None:
        mpv_command(self.active, ["cycle", "fullscreen"])
        print(f"fullscreen toggled on tile {self.active + 1}")

    def respawn_dead(self) -> None:
        for index in range(len(self.streams)):
            proc = self.procs.get(index)
            if proc is None or proc.poll() is not None:
                print(f"tile {index + 1} died, respawning")
                self.kill(index)
                self.spawn(index)
                if index == self.active:
                    time.sleep(2)
                    self.set_audio(index)


def read_key() -> str | None:
    """One keypress, unbuffered. Returns None if stdin isn't a terminal."""
    import select
    import termios
    import tty

    if not sys.stdin.isatty():
        return None

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        if select.select([sys.stdin], [], [], 1.0)[0]:
            return sys.stdin.read(1)
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


@dataclass(frozen=True)
class WallConfig:
    streams: list[str]
    quality: str
    ytdl_format: str
    screen: tuple[int, int] | None
    screen_index: int | None


def load_config(path: Path = CONFIG_PATH) -> WallConfig:
    # utf-8-sig: editors on Windows write a BOM, which tomllib rejects outright.
    data = tomllib.loads(path.read_text(encoding="utf-8-sig"))

    # Blank entries are placeholders for streams not yet announced; drop them so
    # the wall runs with however many are actually filled in.
    streams = [s.strip() for s in data.get("streams", []) if s.strip()]
    if not streams:
        raise SystemExit(
            f"No streams configured in {path}\n"
            "Run `python3 wall/find_streams.py` to find the day's TI streams."
        )

    screen_cfg = data.get("screen", {})
    width, height = screen_cfg.get("width", 0), screen_cfg.get("height", 0)
    index = screen_cfg.get("index", -1)

    return WallConfig(
        streams=streams,
        quality=data.get("quality", "720p60,720p,best"),
        ytdl_format=data.get("ytdl_format", ""),
        screen=(width, height) if width and height else None,
        screen_index=index if index >= 0 else None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="print commands and geometry, spawn nothing")
    parser.add_argument("--width", type=int, help="override detected screen width")
    parser.add_argument("--height", type=int, help="override detected screen height")
    parser.add_argument("--screen", type=int, help="which display to use (0-based)")
    parser.add_argument("--list-displays", action="store_true",
                        help="show attached displays and their indices, then exit")
    args = parser.parse_args()

    if args.list_displays:
        out = subprocess.run(["system_profiler", "SPDisplaysDataType"],
                             capture_output=True, text=True, timeout=30).stdout
        displays = parse_displays(out)
        chosen = choose_display(displays)
        for index, display in enumerate(displays):
            marker = "<- default" if chosen and index == chosen[0] else ""
            w, h = display.logical_size
            print(f"  --screen={index}  {display.name:<24} {w}x{h}"
                  f"{' (Retina)' if display.retina else '':<10} {marker}")
        if mirroring_is_on(displays):
            print("\n  Mirroring is ON, so mpv sees only --screen=0 no matter what\n"
                  "  this list says. Switch to Extended Display to address the TV\n"
                  "  separately from the laptop panel.")
        return 0

    config = load_config()
    detected_note = ""

    if args.width and args.height:
        screen = (args.width, args.height)
        screen_index = args.screen or config.screen_index or 0
    elif config.screen:
        screen = config.screen
        screen_index = args.screen if args.screen is not None else (config.screen_index or 0)
    else:
        screen_index, screen, detected_note = detect_display()
        if args.screen is not None:
            screen_index = args.screen
        if config.screen_index is not None:
            screen_index = config.screen_index

    mpv_bin = shutil.which("mpv") or "/usr/local/bin/mpv"
    streamlink_bin = shutil.which("streamlink") or "/usr/local/bin/streamlink"

    wall = Wall(config.streams, config.quality, screen, mpv_bin, streamlink_bin,
                config.ytdl_format, screen_index)

    if detected_note:
        print(f"display: {detected_note}  ->  --screen={screen_index}")

    if args.dry_run:
        print(f"screen: {screen[0]}x{screen[1]} on display {screen_index}")
        print(f"mpv: {mpv_bin}\nstreamlink: {streamlink_bin}\n")
        for index in range(len(config.streams)):
            geometry = tile_geometry(*screen, index=index, count=len(config.streams))
            kind = "youtube" if is_youtube(config.streams[index]) else "twitch"
            print(f"tile {index + 1}  [{kind}]  {geometry.as_mpv_arg()}  {wall.label(index)}")
            print("  " + " ".join(wall.command_for(index)) + "\n")
        return 0

    needed = [("mpv", mpv_bin)]
    if any(not is_youtube(s) for s in config.streams):
        needed.append(("streamlink", streamlink_bin))
    for name, path in needed:
        if not Path(path).exists():
            raise SystemExit(f"{name} not found. Install with: brew install {name}")

    wall.start_all()
    print("\nkeys:  1-4 audio   5 fullscreen   r respawn dead tiles   q quit")
    print("streams take a few seconds to appear...\n")

    try:
        while True:
            key = read_key()
            if key is None:
                # Not a terminal (e.g. plain `ssh host python3 wall.py`). Stay up
                # so the wall still runs, but hotkeys are unavailable.
                time.sleep(5)
                wall.respawn_dead()
                continue

            # `key` is "" when the read timed out; guard it, because "" is a
            # substring of every string and would match the digit test below.
            if key and key in "1234"[:len(config.streams)]:
                wall.set_audio(int(key) - 1)
            elif key == "5":
                wall.toggle_fullscreen()
            elif key == "r":
                wall.respawn_dead()
            elif key == "q":
                break
            elif key == "":
                wall.respawn_dead()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nshutting down...")
        wall.stop_all()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
