"""Prints every live league game grouped by league, so you can find TI's league_id.

League ids change every tournament, so hardcoding one guarantees a broken scoreboard
next year. Run this while TI is live; the league with tens of thousands of spectators
is the one you want. Paste its id into config.toml.

    python scripts/find_league.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scoreboard.config import load_config  # noqa: E402
from scoreboard.models import parse_live_games  # noqa: E402
from scoreboard.source import SourceError, ValveSource  # noqa: E402


def main() -> int:
    config = load_config()
    source = ValveSource(config.require_key())

    try:
        payload = source.fetch_live_games()
    except SourceError as exc:
        print(f"Could not reach Valve's API: {exc}", file=sys.stderr)
        return 1

    games = parse_live_games(payload, league_id=None)
    if not games:
        print("No live league games at all right now. Try again once TI is on.")
        return 0

    by_league: dict[int, list] = defaultdict(list)
    for game in games:
        by_league[game.league_id].append(game)

    # Biggest audience first - TI will be unmistakable at the top.
    ranked = sorted(
        by_league.items(),
        key=lambda kv: sum(g.spectators for g in kv[1]),
        reverse=True,
    )

    print(f"{len(games)} live game(s) across {len(ranked)} league(s):\n")
    for league_id, league_games in ranked:
        total = sum(g.spectators for g in league_games)
        print(f"  league_id = {league_id:<8}  {len(league_games)} game(s)  {total:,} spectators")
        for game in league_games:
            print(
                f"      {game.radiant.name} vs {game.dire.name}"
                f"   [{game.series_score}]  {game.clock}"
                f"   {game.radiant.score}-{game.dire.score}"
                f"   ({game.spectators:,} watching)"
            )
        print()

    print(f"Put the right one in config.toml as:  league_id = {ranked[0][0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
