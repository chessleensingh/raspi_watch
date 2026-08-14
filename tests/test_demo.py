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


# ---- scripted showcase items -------------------------------------------
# Demo mode exists to show the thing working when nothing is live. That has to
# include the moments worth watching for, one per tile, or the demo shows only
# the parts that were never in doubt.

RAPIER, AEGIS, SMOKE = 133, 117, 188


BASE = 1_000_000.0


def games_at(second):
    """One source, asked about different moments -- which is how the server
    uses it when backfilling history. Building a fresh source per moment resets
    its start time and every snapshot comes out identical."""
    source = DemoSource(league_id=LEAGUE, now=lambda: BASE)
    return parse_live_games(source.payload_at(BASE + second), LEAGUE)


def test_game_one_shows_a_rapier():
    game = games_at(0)[0]

    assert game.radiant.has_rapier is True
    assert game.radiant.rapier_heroes, "no hero named, so no portrait to mark"


def test_game_two_shows_an_aegis():
    game = games_at(0)[1]

    assert game.dire.has_aegis is True


def test_game_three_carries_a_smoke_that_gets_used():
    """The haze needs a DROP between two snapshots, not merely a smoke held."""
    held = [games_at(t)[2].radiant.smoke_count for t in range(0, 180, 10)]

    assert max(held) > 0, "never holds a smoke, so it can never use one"
    assert min(held) == 0, "never uses it, so the haze never fires"


def test_the_fourth_game_stays_plain():
    """A control tile, so the marked ones are visibly different."""
    game = games_at(0)[3]

    assert not game.radiant.has_rapier and not game.dire.has_rapier
    assert not game.radiant.has_aegis and not game.dire.has_aegis


def test_payload_at_is_a_function_of_the_moment_asked_for():
    """Backfilled history must differ per snapshot; identical history detects
    no change at all, which is what the smoke haze is built on."""
    early = games_at(0)[0].duration
    later = games_at(300)[0].duration

    assert later == early + 300


def test_every_game_still_has_a_full_draft():
    for game in games_at(0):
        assert len(game.radiant.picks) == 5
        assert len(game.dire.picks) == 5


def test_history_before_the_source_started_still_moves():
    """Backfill asks about moments BEFORE the source was constructed.

    Clamping elapsed time at zero made every one of those identical, so the
    smoke haze -- which fires on a change between two snapshots -- could never
    trigger in the one mode built to demonstrate it.
    """
    source = DemoSource(league_id=LEAGUE, now=lambda: BASE)

    earlier = parse_live_games(source.payload_at(BASE - 300), LEAGUE)[0].duration
    later = parse_live_games(source.payload_at(BASE), LEAGUE)[0].duration

    assert earlier < later


def test_a_clock_never_runs_negative():
    """Game 4 starts at 01:35; asked about ten minutes ago it must read 00:00,
    not a negative duration."""
    source = DemoSource(league_id=LEAGUE, now=lambda: BASE)

    game = parse_live_games(source.payload_at(BASE - 600), LEAGUE)[3]

    assert game.duration == 0
