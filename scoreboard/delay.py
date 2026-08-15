"""Spoiler guard.

Valve's API is live. The Twitch broadcast is 2-5 minutes behind it. Rendering the
API directly means the scoreboard shows you a kill before you watch it happen, which
ruins every fight of the tournament.

So the poller writes snapshots in here with a timestamp, and reads ask for the state
as it was `delay_seconds` ago. Poll cadence and display delay stay independent.
"""

from __future__ import annotations

import threading
from bisect import bisect_left, bisect_right
from collections import deque
from dataclasses import dataclass
from typing import Any

DEFAULT_RETENTION_SECONDS = 900.0


@dataclass(frozen=True)
class DelayedResult:
    games: list[Any]
    warming_up: bool
    """True when the buffer does not yet span the requested delay, so the data shown
    is fresher than asked for. The UI must say so rather than quietly spoiling."""
    snapshot_age: float | None
    """Seconds between the shown snapshot and `now`. None when nothing is buffered."""


class DelayBuffer:
    """Time-indexed ring of snapshots, safe for one writer and many readers."""

    def __init__(self, retention_seconds: float = DEFAULT_RETENTION_SECONDS) -> None:
        if retention_seconds <= 0:
            raise ValueError("retention_seconds must be positive")
        self._retention = retention_seconds
        self._times: deque[float] = deque()
        self._snapshots: deque[Any] = deque()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._times)

    @property
    def retention_seconds(self) -> float:
        return self._retention

    def append(self, games: Any, timestamp: float) -> None:
        with self._lock:
            if self._times and timestamp < self._times[-1]:
                raise ValueError(
                    "timestamps must be monotonic; the poller is single-threaded "
                    f"but got {timestamp} after {self._times[-1]}"
                )
            self._times.append(timestamp)
            self._snapshots.append(games)
            self._evict(now=timestamp)

    def _evict(self, now: float) -> None:
        """Drop snapshots past the retention window.

        Always keeps the newest entry: after a long polling outage every snapshot is
        stale, and an empty buffer would leave the UI with nothing at all to show.
        """
        cutoff = now - self._retention
        while len(self._times) > 1 and self._times[0] < cutoff:
            self._times.popleft()
            self._snapshots.popleft()

    def snapshots_between(self, start: float, end: float, now: float) -> list:
        """[(timestamp, games)] for snapshots in [start, end], oldest first.

        Exists because comparing only the two ENDS of a window is blind to
        anything that rose and fell inside it: a smoke bought and used between
        two polls reads zero at both ends and looks like nothing happened.

        `end` is a wall-clock time the caller has already offset by the display
        delay, so this returns history and never a peek ahead.
        """
        with self._lock:
            lo = bisect_left(self._times, start)
            hi = bisect_right(self._times, end)
            return [(self._times[i], self._snapshots[i]) for i in range(lo, hi)]

    def get_delayed(self, delay_seconds: float, now: float) -> DelayedResult:
        if delay_seconds < 0:
            raise ValueError("delay_seconds must not be negative")
        if delay_seconds > self._retention:
            raise ValueError(
                f"delay_seconds={delay_seconds} exceeds retention={self._retention}; "
                "the snapshot needed would already have been evicted"
            )

        with self._lock:
            if not self._times:
                return DelayedResult(games=[], warming_up=True, snapshot_age=None)

            target = now - delay_seconds
            # Rightmost snapshot with timestamp <= target. Inclusive, so a target
            # landing exactly on a poll uses that poll.
            idx = bisect_right(self._times, target) - 1

            if idx < 0:
                # Buffer does not reach back far enough yet. Serve the oldest we have
                # rather than something fresher than the viewer asked for.
                return DelayedResult(
                    games=self._snapshots[0],
                    warming_up=True,
                    snapshot_age=now - self._times[0],
                )

            return DelayedResult(
                games=self._snapshots[idx],
                warming_up=False,
                snapshot_age=now - self._times[idx],
            )
