"""Turns wall/streams.toml entries into something a browser can embed.

The viewer is a browser, and an embed needs a concrete video id -- so the
"@channel/live" form, which resolves to a different video every day, cannot be
embedded at all and degrades to an empty slot here.

(The directory is called wall/ for historical reasons: this started as a 2x2
video wall driven from a second machine. That half is gone; the stream list
stayed where it was rather than breaking every path that points at it.)
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
    title: str = ""
    """The broadcast's own title, e.g. "[EN-A] Team Falcons vs. LGD Gaming".

    Valve's game payload carries nothing identifying which stream is showing a
    match, but the stream's title names the teams -- so this is the only thread
    connecting the two, and it is what lets the scoreboard map a game to its
    stream instead of guessing from screen position."""

    def to_dict(self) -> dict:
        return asdict(self)


def _resolve(entry: str, index: int, title: str = "") -> Stream:
    entry = entry.strip()
    if not entry:
        return Stream(index=index, kind="empty", id="", label="no stream configured",
                      title=title)

    if not entry.startswith("http"):
        # A bare name is a Twitch channel.
        return Stream(index=index, kind="twitch", id=entry,
                      label=f"twitch.tv/{entry}", title=title)

    parsed = urlparse(entry)
    host = parsed.netloc.lower()

    if "youtu.be" in host:
        video_id = parsed.path.lstrip("/")
        if video_id:
            return Stream(index=index, kind="youtube", id=video_id, label=entry,
                          title=title)

    if "youtube.com" in host:
        # Only ?v= carries an embeddable id. /@channel/live resolves to a
        # different video every day and cannot be embedded, so it lands below.
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if video_id:
            return Stream(index=index, kind="youtube", id=video_id, label=entry,
                          title=title)

    return Stream(index=index, kind="empty", id="", label=f"cannot embed: {entry}",
                  title=title)


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

    # Optional, and optional-length: files written before titles existed must
    # still load, and a partial list must not shorten the stream list.
    titles = data.get("titles")
    if not isinstance(titles, list):
        titles = []

    return [
        _resolve(str(entry), index,
                 str(titles[index]) if index < len(titles) else "")
        for index, entry in enumerate(entries)
    ]
