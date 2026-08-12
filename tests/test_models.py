"""Tests for normalizing Valve's GetLiveLeagueGames payload.

The payload is inconsistent in ways that matter: games in the draft phase have no
`scoreboard` key at all, unregistered teams have no `*_team` object, and `players`
can be short. All of that happens routinely during a real tournament.
"""

import json
from pathlib import Path

import pytest

from scoreboard.models import Game, parse_live_games

FIXTURE = Path(__file__).parent / "fixtures" / "live_league_games.json"
TI_LEAGUE_ID = 18324


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_filters_to_the_requested_league(payload):
    games = parse_live_games(payload, league_id=TI_LEAGUE_ID)

    assert len(games) == 3
    assert all(g.league_id == TI_LEAGUE_ID for g in games)


def test_no_league_filter_returns_everything(payload):
    assert len(parse_live_games(payload, league_id=None)) == 4


def test_parses_a_game_in_progress(payload):
    game = parse_live_games(payload, league_id=TI_LEAGUE_ID)[0]

    assert game.match_id == 8123456789
    assert game.radiant.name == "Team Spirit"
    assert game.dire.name == "Gaimin Gladiators"
    assert game.radiant.score == 23
    assert game.dire.score == 17
    assert game.radiant.series_wins == 1
    assert game.dire.series_wins == 0
    assert game.in_progress is True


def test_clock_formats_duration_as_minutes_and_seconds(payload):
    game = parse_live_games(payload, league_id=TI_LEAGUE_ID)[0]

    # 2115.6376 seconds -> 35:15
    assert game.clock == "35:15"


def test_net_worth_is_summed_per_side(payload):
    game = parse_live_games(payload, league_id=TI_LEAGUE_ID)[0]

    assert game.radiant.net_worth == 21450 + 17300 + 14100 + 11250 + 9900
    assert game.dire.net_worth == 18600 + 15400 + 12800 + 10050 + 8300


def test_net_worth_lead_names_the_leading_side_and_the_gap(payload):
    game = parse_live_games(payload, league_id=TI_LEAGUE_ID)[0]

    side, amount = game.net_worth_lead
    assert side == "radiant"
    assert amount == game.radiant.net_worth - game.dire.net_worth


def test_picks_and_bans_are_hero_ids(payload):
    game = parse_live_games(payload, league_id=TI_LEAGUE_ID)[0]

    assert game.radiant.picks == (1, 8, 26, 74, 114)
    assert game.dire.bans == (39, 63, 22)


def test_game_without_scoreboard_still_parses(payload):
    """Drafting games have no `scoreboard` key. They must appear, not crash."""
    game = parse_live_games(payload, league_id=TI_LEAGUE_ID)[1]

    assert game.match_id == 8123456790
    assert game.in_progress is False
    assert game.clock == "--:--"
    assert game.radiant.score == 0
    assert game.radiant.net_worth == 0
    assert game.radiant.picks == ()
    assert game.net_worth_lead == ("radiant", 0)


def test_missing_team_object_falls_back_to_a_placeholder(payload):
    """Teams that have not registered a name still play games."""
    game = parse_live_games(payload, league_id=TI_LEAGUE_ID)[2]

    assert game.radiant.name == "Radiant"
    assert game.radiant.team_id is None
    assert game.dire.name == "Nigma Galaxy"


def test_missing_picks_key_is_treated_as_empty(payload):
    """The dire side of the third game has no `picks` key at all."""
    game = parse_live_games(payload, league_id=TI_LEAGUE_ID)[2]

    assert game.dire.picks == ()


def test_stream_delay_is_read_from_the_payload(payload):
    """Valve tells us the broadcast delay, so the user should not have to guess."""
    game = parse_live_games(payload, league_id=TI_LEAGUE_ID)[0]

    assert game.stream_delay == 120


def test_missing_stream_delay_is_none_not_zero(payload):
    """Zero would mean 'no delay needed' and spoil every fight. Absent is absent."""
    game = parse_live_games(payload, league_id=TI_LEAGUE_ID)[2]

    assert game.stream_delay is None


def test_empty_payload_is_not_an_error():
    assert parse_live_games({"result": {"games": []}}, league_id=TI_LEAGUE_ID) == []
    assert parse_live_games({"result": {}}, league_id=TI_LEAGUE_ID) == []
    assert parse_live_games({}, league_id=TI_LEAGUE_ID) == []


def test_games_are_ordered_stably_by_match_id(payload):
    """Tile positions must not jump around between polls.

    Valve orders by spectator count, which reorders constantly as viewers move
    between streams. Sorting by match_id keeps each game in a fixed tile.
    """
    games = parse_live_games(payload, league_id=TI_LEAGUE_ID)
    assert [g.match_id for g in games] == sorted(g.match_id for g in games)


def test_game_is_json_serializable(payload):
    game = parse_live_games(payload, league_id=TI_LEAGUE_ID)[0]

    encoded = json.dumps(game.to_dict())
    assert json.loads(encoded)["radiant"]["name"] == "Team Spirit"
