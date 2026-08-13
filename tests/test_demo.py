"""Tests for demo mode.

Valve published no in-progress TI games during the 2026 group stage's first
round, which left no way to exercise the one interaction that matters -- click a
game, the main screen switches. Demo mode supplies stand-in games so that path
can be tested without waiting on Valve.
"""

from scoreboard.demo import DemoSource, MATCHUPS
from scoreboard.models import parse_live_games

LEAGUE = 19719


def test_supplies_one_game_per_stream():
    """Four games against four streams, so game n defaults to stream n."""
    games = parse_live_games(DemoSource(league_id=LEAGUE).fetch_live_games(), LEAGUE)

    assert len(games) == 4


def test_games_carry_the_configured_league_so_the_filter_finds_them():
    source = DemoSource(league_id=LEAGUE)

    assert parse_live_games(source.fetch_live_games(), LEAGUE) != []
    assert parse_live_games(source.fetch_live_games(), 12345) == []


def test_matchups_are_the_real_ones_so_the_mapping_reads_correctly():
    games = parse_live_games(DemoSource(league_id=LEAGUE).fetch_live_games(), LEAGUE)

    assert [g.radiant.name for g in games] == [m[0] for m in MATCHUPS]
    assert [g.dire.name for g in games] == [m[1] for m in MATCHUPS]


def test_the_clock_advances_with_real_time():
    clock = [1000.0]
    source = DemoSource(league_id=LEAGUE, now=lambda: clock[0])
    early = parse_live_games(source.fetch_live_games(), LEAGUE)[0].duration

    clock[0] += 600.0
    later = parse_live_games(source.fetch_live_games(), LEAGUE)[0].duration

    assert later == early + 600.0


def test_games_are_in_progress_not_stuck_in_draft():
    """The real feed only ever offered pregame entries; a demo that did the same
    would not exercise the scoreboard at all."""
    games = parse_live_games(DemoSource(league_id=LEAGUE).fetch_live_games(), LEAGUE)

    assert all(g.in_progress for g in games)
    assert all(g.duration > 0 for g in games)


def test_scores_differ_between_games_so_tiles_are_distinguishable():
    games = parse_live_games(DemoSource(league_id=LEAGUE).fetch_live_games(), LEAGUE)

    assert len({(g.radiant.score, g.dire.score) for g in games}) > 1


def test_heroes_are_served_so_the_draft_toggle_works():
    heroes = DemoSource(league_id=LEAGUE).fetch_heroes()

    assert heroes["result"]["heroes"], "no heroes; the Drafts toggle would be empty"


def test_a_reported_stream_delay_is_present_for_the_delay_readout():
    games = parse_live_games(DemoSource(league_id=LEAGUE).fetch_live_games(), LEAGUE)

    assert all(g.stream_delay for g in games)
