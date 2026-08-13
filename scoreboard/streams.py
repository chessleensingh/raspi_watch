"""Turns wall/streams.toml entries into something a browser can embed.

One stream list, two consumers with different needs. wall.py hands entries to
mpv and streamlink, which happily take a channel page URL and resolve it
themselves. The viewer is a browser, and an embed needs a concrete video ID --
so the "@channel/live" form, which mpv accepts, cannot be embedded at all and
degrades to an empty slot here.

This module deliberately imports nothing from wall/: that package carries
macOS-only concerns (system_profiler, mpv IPC sockets) and must not be dragged
into the Windows-side server. It only reads the file.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).parent.parent / "wall" / "streams.toml"


@dataclass(frozen=True)
class Stream:
    index: int
    kind: str
    """One of "youtube", "twitch", or "empty"."""
    id: str
    """A YouTube video id, or a Twitch channel name. Empty when kind is "empty"."""
    label: str
    """What the viewer shows in the corner, so a wrong slot is obvious on sight."""

    def to_dict(self) -> dict:
        return asdict(self)


def _resolve(entry: str, index: int) -> Stream:
    entry = entry.strip()
    if not entry:
        return Stream(index=index, kind="empty", id="", label="no stream configured")

    if not entry.startswith("http"):
        # Matches wall.py's convention: a bare name is a Twitch channel.
        return Stream(index=index, kind="twitch", id=entry, label=f"twitch.tv/{entry}")

    parsed = urlparse(entry)
    host = parsed.netloc.lower()

    if "youtu.be" in host:
        video_id = parsed.path.lstrip("/")
        if video_id:
            return Stream(index=index, kind="youtube", id=video_id, label=entry)

    if "youtube.com" in host:
        # Only ?v= carries an embeddable id. /@channel/live resolves to a
        # different video every day and cannot be embedded, so it lands below.
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if video_id:
            return Stream(index=index, kind="youtube", id=video_id, label=entry)

    return Stream(index=index, kind="empty", id="", label=f"cannot embed: {entry}")


def load_streams(path: Path | None = None) -> list[Stream]:
    """Reads the stream list. Never raises: a broken stream config must not stop
    the scoreboard from starting, since the scores matter more than the video."""
    path = path or DEFAULT_PATH
    try:
        # utf-8-sig: editors on Windows write a BOM, which tomllib rejects.
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        log.warning("no stream list at %s; the viewer will have nothing to show", path)
        return []
    except (tomllib.TOMLDecodeError, OSError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return []

    entries = data.get("streams")
    if not isinstance(entries, list):
        return []

    return [_resolve(str(entry), index) for index, entry in enumerate(entries)]
