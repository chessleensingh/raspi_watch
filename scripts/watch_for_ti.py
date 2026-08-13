"""Polls until Valve publishes an IN-PROGRESS game for the configured league.

Why this exists: on 2026-08-12, TI matches appeared in GetLiveLeagueGames only
during draft -- every entry had a clock of "--:--" or "00:00" -- and vanished
once play started. So the scoreboard could name the matchup and never show a
score, which is the one thing it exists to do.

Whether that is deliberate or a first-day glitch is unknown, so this watches for
it to change rather than assuming either way.

    python scripts/watch_for_ti.py                # checks every 3 minutes
    python scripts/watch_for_ti.py --interval 60

An earlier version of this ranked leagues by spectator count, which could never
have worked: Valve reports 0 spectators for TI games. That is also why
find_league.py's suggestion points at an amateur league during TI -- the real
one is found by recognising the team names, not by size.
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

def check(source, league_id):
    """A game in our league that has actually started."""
    games = parse_live_games(source.fetch_live_games(), league_id=league_id)
    return [g for g in games if g.in_progress]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interval", type=float, default=180.0,
                        help="seconds between checks (default 180)")
    parser.add_argument("--max-hours", type=float, default=6.0,
                        help="give up after this long (default 6)")
    args = parser.parse_args()

    config = load_config()
    if config.league_id is None:
        print("No league_id set in config.toml; nothing to watch.")
        return 1

    source = ValveSource(config.require_key())
    deadline = time.time() + args.max_hours * 3600

    while time.time() < deadline:
        try:
            found = check(source, config.league_id)
        except SourceError as exc:
            # Valve's API falls over during TI; that is not a reason to stop.
            print(f"  API error, will retry: {exc}", flush=True)
            found = []

        if found:
            print(f"\nVALVE IS PUBLISHING LIVE TI SCORES NOW "
                  f"({len(found)} game(s) in progress):")
            for game in found:
                print(f"    {game.radiant.name} vs {game.dire.name}  {game.clock}")
            print("\nThe scoreboard fills in on its own within a poll or two.")
            return 0

        print(f"  {time.strftime('%H:%M:%S')}  league {config.league_id}: "
              f"nothing with a running clock yet", flush=True)
        time.sleep(args.interval)

    print("Gave up waiting. Re-run when the next round starts.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
