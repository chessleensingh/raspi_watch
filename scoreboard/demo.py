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

# Scripted so each tile demonstrates one thing, with a plain fourth as a
# control -- a demo where every tile is lit up shows nothing.
RAPIER_ITEM_ID = 133
AEGIS_ITEM_ID = 117
SMOKE_ITEM_ID = 188

# Game 3's smoke is bought and used on a loop, because the haze fires on a smoke
# LEAVING an inventory. A demo that only ever holds one would never show it.
# Tuned against how the detection actually works, not by feel. The server
# compares two snapshots exactly SMOKE_WINDOW_SECONDS (40s) apart and flags a
# DROP, so the haze is on only while the older sample holds a smoke and the
# newer does not. Making the hold exactly half the period puts those two samples
# permanently out of phase, which is the most a square wave can give: on half
# the time, alternating every 40s. A shorter hold looked more "realistic" and
# fired under a fifth of the time -- a demo you have to wait around for does not
# get shown.
SMOKE_PERIOD = 80.0
SMOKE_HELD_FOR = 40.0

_HEROES = [
    (1, "npc_dota_hero_antimage"), (8, "npc_dota_hero_juggernaut"),
    (11, "npc_dota_hero_nevermore"), (14, "npc_dota_hero_pudge"),
    (19, "npc_dota_hero_tiny"), (22, "npc_dota_hero_zuus"),
    (25, "npc_dota_hero_lina"), (35, "npc_dota_hero_sniper"),
    (44, "npc_dota_hero_phantom_assassin"), (74, "npc_dota_hero_invoker"),
]


def _scripted_item(index: int, side: int, seconds: float) -> int:
    """The one showcase item this side is holding, or 0.

    Tile 1 a Rapier, tile 2 an Aegis, tile 3 a Smoke that comes and goes, tile 4
    nothing at all.
    """
    if index == 0 and side == 0:
        return RAPIER_ITEM_ID
    if index == 1 and side == 1:
        return AEGIS_ITEM_ID
    if index == 2 and side == 0:
        return SMOKE_ITEM_ID if (seconds % SMOKE_PERIOD) < SMOKE_HELD_FOR else 0
    return 0


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
            {
                "hero_id": _HEROES[(index * 5 + side * 2 + p) % len(_HEROES)][0],
                "net_worth": int(base * (1.0 + 0.14 * p)),
                # The showcase item rides on the first player, so the Rapier
                # outline lands on a hero that is actually in the draft column.
                "item0": _scripted_item(index, side, seconds) if p == 0 else 0,
                **{f"item{slot}": 0 for slot in range(1, 6)},
            }
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
        return self.payload_at(self._now())

    def payload_at(self, moment: float) -> dict:
        """The world as it looked at `moment`.

        Backfilled history has to differ per snapshot. Generating every
        backdated snapshot from "now" makes them identical, and the smoke haze
        -- which fires on a CHANGE between two snapshots -- can then never
        trigger, in a mode built to demonstrate exactly that.
        """
        # NOT clamped at zero. Backfill asks about moments before this source
        # was constructed, and clamping made every one of them identical -- so
        # nothing ever changed between snapshots and the smoke haze, which fires
        # on exactly that change, could never trigger.
        elapsed = moment - self._started
        games = []
        for index, (radiant, dire) in enumerate(MATCHUPS):
            # Clamp the CLOCK instead, per game: a match cannot have started
            # before 00:00 however far back you ask.
            seconds = max(0.0, _OFFSETS[index] + elapsed)
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
