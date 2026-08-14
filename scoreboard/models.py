"""Normalizes Valve's GetLiveLeagueGames payload into something the UI can render.

Valve's payload is loose: `scoreboard` is absent during the draft, `radiant_team` is
absent for unregistered teams, and `picks`/`players` come and go. Everything here
degrades to a sane default rather than raising, because a scoreboard that drops a
tile mid-tournament is worse than one showing "--:--".

This module is the seam for swapping data sources. `source.py` returns raw dicts;
if Valve's API goes down mid-TI, an OpenDota adapter only has to produce `Game`s.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Valve's item ids, confirmed against Dota's own item constants rather than
# recalled. These two are the moments worth looking up from your phone for.
RAPIER_ITEM_ID = 133
AEGIS_ITEM_ID = 117


@dataclass(frozen=True)
class Side:
    """One team's state in one game."""

    name: str
    team_id: int | None
    logo: int | None
    series_wins: int
    score: int
    """Kills."""
    net_worth: int
    picks: tuple[int, ...] = ()
    bans: tuple[int, ...] = ()
    tower_state: int = 0
    barracks_state: int = 0
    items: tuple[int, ...] = ()
    """Every item id held across this side's five players, all six slots each."""
    rapier_heroes: tuple[int, ...] = ()
    """Hero ids currently holding a Divine Rapier.

    Kept per hero, not merely as a flag, so the mark can go on that hero's
    portrait in the draft rather than on the whole tile -- where it competed
    with the active-stream outline and said only "something happened here"."""

    @property
    def has_rapier(self) -> bool:
        return bool(self.rapier_heroes)

    @property
    def has_aegis(self) -> bool:
        return AEGIS_ITEM_ID in self.items


@dataclass(frozen=True)
class Game:
    match_id: int
    league_id: int
    lobby_id: int | None
    spectators: int
    duration: float | None
    """None while the game has not started; the scoreboard key is absent then."""
    stream_delay: int | None
    """Broadcast delay in seconds, straight from Valve. None when absent -- which
    must not be read as zero, since zero would mean "show live data" and spoil
    every fight. Observed values in the wild: 10, 120, 300."""
    series_type: int
    radiant: Side
    dire: Side

    @property
    def in_progress(self) -> bool:
        return self.duration is not None

    @property
    def clock(self) -> str:
        if self.duration is None:
            return "--:--"
        total = int(self.duration)
        return f"{total // 60:02d}:{total % 60:02d}"

    @property
    def net_worth_lead(self) -> tuple[str, int]:
        """(leading side, gold advantage). Ties and pre-game both report radiant/0."""
        diff = self.radiant.net_worth - self.dire.net_worth
        return ("radiant", diff) if diff >= 0 else ("dire", -diff)

    @property
    def series_score(self) -> str:
        return f"{self.radiant.series_wins}-{self.dire.series_wins}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["clock"] = self.clock
        data["in_progress"] = self.in_progress
        data["series_score"] = self.series_score
        side, amount = self.net_worth_lead
        data["net_worth_lead"] = {"side": side, "amount": amount}
        # Properties are not fields, so asdict misses them.
        for name in ("radiant", "dire"):
            source = getattr(self, name)
            data[name]["has_rapier"] = source.has_rapier
            data[name]["has_aegis"] = source.has_aegis
        return data


_DEFAULT_NAMES = {"radiant": "Radiant", "dire": "Dire"}


def _parse_side(game: dict, board: dict | None, side: str) -> Side:
    team = game.get(f"{side}_team") or {}
    board_side = (board or {}).get(side) or {}
    players = board_side.get("players") or []

    return Side(
        name=team.get("team_name") or _DEFAULT_NAMES[side],
        team_id=team.get("team_id"),
        logo=team.get("team_logo"),
        series_wins=game.get(f"{side}_series_wins") or 0,
        score=board_side.get("score") or 0,
        net_worth=sum(p.get("net_worth") or 0 for p in players),
        picks=tuple(p["hero_id"] for p in board_side.get("picks") or [] if "hero_id" in p),
        bans=tuple(b["hero_id"] for b in board_side.get("bans") or [] if "hero_id" in b),
        tower_state=board_side.get("tower_state") or 0,
        barracks_state=board_side.get("barracks_state") or 0,
        # item0..item5 per player. An id of 0 means an empty slot.
        items=tuple(
            item for p in players
            for item in (p.get(f"item{slot}") or 0 for slot in range(6))
            if item
        ),
        rapier_heroes=tuple(
            p["hero_id"] for p in players
            if p.get("hero_id")
            and any(p.get(f"item{slot}") == RAPIER_ITEM_ID for slot in range(6))
        ),
    )


def parse_live_games(payload: dict, league_id: int | None) -> list[Game]:
    """Normalize a GetLiveLeagueGames response.

    `league_id=None` returns every live game, which is what `scripts/find_league.py`
    uses to discover TI's id on the day.
    """
    raw_games = (payload or {}).get("result", {}).get("games") or []

    games = []
    for raw in raw_games:
        if league_id is not None and raw.get("league_id") != league_id:
            continue

        board = raw.get("scoreboard")
        games.append(
            Game(
                match_id=raw.get("match_id") or 0,
                league_id=raw.get("league_id") or 0,
                lobby_id=raw.get("lobby_id"),
                spectators=raw.get("spectators") or 0,
                duration=board.get("duration") if board else None,
                stream_delay=raw.get("stream_delay_s"),
                series_type=raw.get("series_type") or 0,
                radiant=_parse_side(raw, board, "radiant"),
                dire=_parse_side(raw, board, "dire"),
            )
        )

    # Valve orders by spectator count, which churns constantly as viewers switch
    # streams. Sorting by match_id pins each game to a fixed tile.
    games.sort(key=lambda g: g.match_id)
    return games
