"""Stand-in games, for when Valve is publishing none.

During TI 2026's first round Valve's live feed carried TI matches only around
the draft and dropped them once play started, so the scoreboard had nothing to
show and the one interaction that matters -- click a game, the main screen
switches to it -- could not be exercised at all.

This produces the same payload shape as GetLiveLeagueGames, so everything
downstream (parsing, the delay buffer, the API, the page) runs exactly as it
does against the real thing. Only the source differs.

    python -m scoreboard.server --demo

The four matchups are the real ones being broadcast, in stream order, so game n
maps to stream n by default and the badge mapping reads correctly.
"""

from __future__ import annotations

import time

# In the order streams.toml lists them: EN-A, EN-B, EN-C, EN-D.
MATCHUPS = [
    ("Team Falcons", "LGD Gaming"),
    ("Nigma Galaxy", "Iron Wing"),
    ("BoomBoys", "OG"),
    ("Team Resilience", "TEAM VISION"),
]

# Distinct starting points so the tiles are visibly different from each other
# and from one another's scores -- a demo where every tile reads the same tests
# nothing about which game you clicked.
# None start at zero: a tile reading 00:00 is exactly the pregame state
# that made the real feed useless here.
_OFFSETS = [640, 420, 1080, 95]
_SCORE_RATES = [(38.0, 51.0), (61.0, 44.0), (47.0, 47.0), (72.0, 96.0)]

# Matches what Valve reports for a real broadcast, so the delay readout says
# "from Valve" and the spoiler guard behaves as it will on live data.
STREAM_DELAY_SECONDS = 120

_HEROES = [
    (1, "npc_dota_hero_antimage"), (8, "npc_dota_hero_juggernaut"),
    (11, "npc_dota_hero_nevermore"), (14, "npc_dota_hero_pudge"),
    (19, "npc_dota_hero_tiny"), (22, "npc_dota_hero_zuus"),
    (25, "npc_dota_hero_lina"), (35, "npc_dota_hero_sniper"),
    (44, "npc_dota_hero_phantom_assassin"), (74, "npc_dota_hero_invoker"),
]


def _side(index: int, side: int, seconds: float) -> dict:
    """One team's live numbers, drifting with the clock."""
    rate = _SCORE_RATES[index][side]
    score = int(seconds / rate)
    # Net worth grows steadily and unevenly, so the lead bar has something to
    # show and does not sit pinned at "even".
    base = 600 + seconds * (1.9 + 0.35 * side + 0.2 * index)
    return {
        "score": score,
        "tower_state": 2047,
        "barracks_state": 63,
        "players": [
            {"hero_id": _HEROES[(index * 5 + side * 2 + p) % len(_HEROES)][0],
             "net_worth": int(base * (1.0 + 0.14 * p))}
            for p in range(5)
        ],
        "picks": [{"hero_id": _HEROES[(index * 5 + side * 3 + p) % len(_HEROES)][0]}
                  for p in range(5)],
        "bans": [],
    }


class DemoSource:
    """Drop-in for ValveSource that invents four plausible games."""

    def __init__(self, league_id: int | None = None, now=time.time) -> None:
        self.league_id = league_id or 0
        self._now = now
        self._started = now()

    def fetch_live_games(self) -> dict:
        elapsed = max(0.0, self._now() - self._started)
        games = []
        for index, (radiant, dire) in enumerate(MATCHUPS):
            seconds = _OFFSETS[index] + elapsed
            games.append({
                "match_id": 9000000000 + index,
                "league_id": self.league_id,
                "lobby_id": 1000 + index,
                "spectators": 0,
                "stream_delay_s": STREAM_DELAY_SECONDS,
                "series_type": 1,
                "radiant_team": {"team_name": radiant, "team_id": 100 + index},
                "dire_team": {"team_name": dire, "team_id": 200 + index},
                "radiant_series_wins": index % 2,
                "dire_series_wins": (index + 1) % 2,
                "scoreboard": {
                    "duration": seconds,
                    "radiant": _side(index, 0, seconds),
                    "dire": _side(index, 1, seconds),
                },
            })
        return {"result": {"games": games}}

    def fetch_heroes(self) -> dict:
        return {"result": {"heroes": [{"id": i, "name": n} for i, n in _HEROES]}}
