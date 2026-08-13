"""Polls until TI's games appear in Valve's live feed, then prints the league id.

Why this exists: on 2026-08-12 the broadcast was live and the matches were being
played, but GetLiveLeagueGames listed only amateur leagues -- no TI game in it at
all, and OpenDota's live endpoint agreed. So the scoreboard had nothing to show
through no fault of its own, and the only way to know when that changed was to
keep asking.

    python scripts/watch_for_ti.py                # checks every 3 minutes
    python scripts/watch_for_ti.py --interval 60

Stops as soon as it finds a league big enough to be TI, and prints the line to
paste into config.toml.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scoreboard.config import load_config  # noqa: E402
from scoreboard.models import parse_live_games  # noqa: E402
from scoreboard.source import SourceError, ValveSource  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# TI draws six figures. Anything this size cannot be an amateur league, and the
# amateur leagues seen during the outage topped out at single-digit spectators.
TI_SPECTATOR_FLOOR = 1000


def check(source) -> tuple[int, int] | None:
    """The biggest league by spectators, if it looks like TI."""
    games = parse_live_games(source.fetch_live_games(), league_id=None)
    if not games:
        return None

    by_league: dict[int, int] = {}
    for game in games:
        by_league[game.league_id] = by_league.get(game.league_id, 0) + (game.spectators or 0)

    league_id, spectators = max(by_league.items(), key=lambda kv: kv[1])
    return (league_id, spectators) if spectators >= TI_SPECTATOR_FLOOR else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interval", type=float, default=180.0,
                        help="seconds between checks (default 180)")
    parser.add_argument("--max-hours", type=float, default=6.0,
                        help="give up after this long (default 6)")
    args = parser.parse_args()

    source = ValveSource(load_config().require_key())
    deadline = time.time() + args.max_hours * 3600

    while time.time() < deadline:
        try:
            found = check(source)
        except SourceError as exc:
            # Valve's API falls over during TI; that is not a reason to stop.
            print(f"  API error, will retry: {exc}", flush=True)
            found = None

        if found:
            league_id, spectators = found
            print(f"\nTI IS LIVE IN THE API: league {league_id}, "
                  f"{spectators:,} spectators")
            print(f"\nPut this in config.toml and restart the server:\n"
                  f"    league_id = {league_id}")
            return 0

        print(f"  {time.strftime('%H:%M:%S')}  still no TI in the feed", flush=True)
        time.sleep(args.interval)

    print("Gave up waiting. Re-run when the next round starts.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
