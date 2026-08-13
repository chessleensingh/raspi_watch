"""Finds the TI streams that are live right now, and prints a block to paste into
streams.toml.

Why this exists: on YouTube, concurrent TI streams are separate video IDs on the
same channel, and those IDs change every day of the event. The "@channel/live"
URL form only resolves to one of them -- and the viewer needs a concrete video
id, since that form cannot be embedded at all. So each morning of the group
stage:

    python wall/find_streams.py              # official Dota 2 YouTube channel
    python wall/find_streams.py -c @PGL      # some other channel
    python wall/find_streams.py --twitch     # probe Twitch channel names instead

Runs on the Windows box, alongside the scoreboard and viewer that consume
streams.toml. Needs yt-dlp (in requirements.txt), and streamlink for --twitch.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys

DEFAULT_CHANNELS = ["@dota2"]

# The four English streams, confirmed by Valve's 2026-08-11 announcement
# ("The International: Streams, Secret Shop, and More"). Unlike the YouTube
# side these names are stable for the whole event, so the wall can just use
# them directly and skip the daily video-ID hunt.
TWITCH_ENGLISH = ["dota2ti", "dota2ti_2", "dota2ti_3", "dota2ti_4"]

# Other languages, same A/B/C/D pattern.
TWITCH_BY_LANGUAGE = {
    "en": TWITCH_ENGLISH,
    "cn": ["dota2ti_cn", "dota2ti_cn_2", "dota2ti_cn_3", "dota2ti_cn_4"],
    "ru": ["dota2ti_ru", "dota2ti_ru_2", "dota2ti_ru_3", "dota2ti_ru_4"],
    "es": ["dota2ti_es", "dota2ti_es_2", "dota2ti_es_3", "dota2ti_es_4"],
}

# Probed in order. The 2026 names first, then the shapes Valve used in earlier
# years, in case they rename mid-event.
TWITCH_CANDIDATES = TWITCH_ENGLISH + [
    "dota2ti_a", "dota2ti_b", "dota2ti_c", "dota2ti_d",
    "dota2ti2", "dota2ti3", "dota2ti4",
    "dota2",
]


def printable(text: str, encoding: str | None = None) -> str:
    """Drops characters the console cannot represent.

    Windows consoles default to cp1252 and stream titles are routinely not:
    em dashes, team tags, CJK. Printing one raw raises UnicodeEncodeError
    halfway through the results, which loses the ids you came for.
    """
    encoding = encoding or sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def yt_dlp_command() -> list[str]:
    """How to invoke yt-dlp here, as an argv prefix.

    On the Mac it is a Homebrew binary on PATH. On Windows `pip install yt-dlp`
    drops yt-dlp.exe into a Scripts directory that frequently is not on PATH,
    so fall back to running the installed module through this interpreter --
    which is the same package, just reached differently.
    """
    found = shutil.which("yt-dlp")
    if found:
        return [found]

    if "yt_dlp" in sys.modules or importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]

    sys.exit("yt-dlp not found. Install it with: pip install yt-dlp")


def find_youtube_live(channel: str, timeout: float = 90.0) -> list[dict]:
    """Live videos on a channel's /streams tab, newest first."""
    url = f"https://www.youtube.com/{channel.lstrip('/')}/streams"

    try:
        result = subprocess.run(
            [*yt_dlp_command(), "--flat-playlist", "--dump-single-json",
             "--playlist-end", "25", url],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        sys.exit("yt-dlp not found. Install it with: pip install yt-dlp")
    except subprocess.TimeoutExpired:
        print(f"  timed out querying {url}", file=sys.stderr)
        return []

    if result.returncode != 0:
        print(f"  yt-dlp failed for {url}: {result.stderr.strip()[:200]}", file=sys.stderr)
        return []

    try:
        data = json.loads(result.stdout)
    except ValueError:
        print(f"  unparseable response for {url}", file=sys.stderr)
        return []

    live = []
    for entry in data.get("entries") or []:
        # yt-dlp reports live_status on the streams tab; fall back to the
        # concurrent viewer count, which only live videos carry.
        is_live = entry.get("live_status") == "is_live" or entry.get("concurrent_view_count")
        if not is_live:
            continue
        video_id = entry.get("id")
        if video_id:
            live.append({
                "id": video_id,
                "title": (entry.get("title") or "").strip(),
                "viewers": entry.get("concurrent_view_count") or 0,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            })
    return live


def probe_twitch(candidates: list[str], timeout: float = 20.0) -> list[str]:
    """Which candidate Twitch channels are actually live."""
    streamlink = shutil.which("streamlink") or "/usr/local/bin/streamlink"
    live = []
    for name in candidates:
        try:
            result = subprocess.run(
                [streamlink, "--json", f"twitch.tv/{name}"],
                capture_output=True, text=True, timeout=timeout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        try:
            payload = json.loads(result.stdout or "{}")
        except ValueError:
            continue
        if payload.get("streams"):
            qualities = ",".join(list(payload["streams"])[:4])
            print(f"  LIVE  twitch.tv/{name}   ({qualities})")
            live.append(name)
        else:
            print(f"  --    twitch.tv/{name}")
    return live


def print_toml_block(entries: list[str], titles: list[str] | None = None) -> None:
    print("\nPaste this into wall/streams.toml:\n")
    print("streams = [")
    for entry in entries[:4]:
        print(f'  "{entry}",')
    for _ in range(max(0, 4 - len(entries))):
        print('  "",')
    print("]")

    # The titles are what let the scoreboard work out which stream a game is on.
    # Valve's payload names no stream, but "[EN-A] Team Falcons vs. LGD Gaming"
    # names both teams. Without them the mapping falls back to screen position,
    # which is right only if the scoreboard happens to list games in stream
    # order -- and it does not, since Valve returns them in its own.
    if titles:
        print("\ntitles = [")
        for title in titles[:4]:
            print(f'  "{printable(title).replace(chr(34), chr(39))}",')
        for _ in range(max(0, 4 - len(titles))):
            print('  "",')
        print("]")

    if len(entries) > 4:
        print(f"\n({len(entries)} live streams found; only the first 4 fit the 2x2 wall.)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-c", "--channel", action="append", dest="channels",
                        help="YouTube channel (repeatable), e.g. @dota2")
    parser.add_argument("--twitch", action="store_true",
                        help="probe Twitch channel names instead of YouTube")
    parser.add_argument("--language", choices=sorted(TWITCH_BY_LANGUAGE),
                        help="with --twitch, probe one language's four streams "
                             "(default: English, then older name shapes)")
    args = parser.parse_args()

    if args.twitch:
        print("Probing Twitch channels (this takes a moment)...\n")
        candidates = (TWITCH_BY_LANGUAGE[args.language] if args.language
                      else TWITCH_CANDIDATES)
        live = probe_twitch(candidates)
        if not live:
            print("\nNothing live. TI 2026 group stage runs Aug 13-16.")
            return 0
        print_toml_block(live)
        return 0

    channels = args.channels or DEFAULT_CHANNELS
    found: list[str] = []
    found_titles: list[str] = []

    for channel in channels:
        print(f"Checking youtube.com/{channel.lstrip('/')}/streams ...")
        live = find_youtube_live(channel)
        if not live:
            print("  nothing live\n")
            continue
        for stream in sorted(live, key=lambda s: s["viewers"], reverse=True):
            viewers = f"{stream['viewers']:,}" if stream["viewers"] else "?"
            print(f"  LIVE  {stream['url']}   {viewers} watching")
            print(f"        {printable(stream['title'][:90])}")
            found.append(stream["url"])
            found_titles.append(stream["title"])
        print()

    if not found:
        print("No live streams found. TI 2026 group stage runs Aug 13-16.")
        print("If Valve is broadcasting elsewhere, try:  --channel @SomeOtherChannel")
        print("or fall back to Twitch with:  --twitch")
        return 0

    print_toml_block(found, found_titles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
