"""Tests for the HTTP layer, against a stubbed source. No network."""

import json
import time
from pathlib import Path

import pytest

from scoreboard.config import Config
from scoreboard.heroes import HeroIndex
from scoreboard.models import parse_live_games
from scoreboard.server import create_app
from scoreboard.source import SourceError
from scoreboard.streams import Stream

FIXTURE = Path(__file__).parent / "fixtures" / "live_league_games.json"
TI_LEAGUE_ID = 18324


class StubSource:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0

    def fetch_live_games(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload

    def fetch_heroes(self):
        return {"result": {"heroes": [{"id": 1, "name": "npc_dota_hero_antimage"}]}}


@pytest.fixture
def config():
    return Config(
        steam_api_key="stub",
        league_id=TI_LEAGUE_ID,
        poll_interval_seconds=15.0,
        default_delay_seconds=120.0,
        retention_seconds=900.0,
        host="127.0.0.1",
        port=8000,
    )


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def app(config, payload):
    source = StubSource(payload=payload)
    heroes = HeroIndex({1: "antimage", 8: "juggernaut"})
    app = create_app(config, source=source, heroes=heroes, start_poller=False)
    app.config["stub_source"] = source
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def seed(app, delay_ago=0.0, payload=None, league_id=TI_LEAGUE_ID):
    """Put one snapshot into the buffer as if polled `delay_ago` seconds back."""
    games = parse_live_games(payload, league_id=league_id)
    app.config["buffer"].append(games, timestamp=time.time() - delay_ago)
    return games


def test_index_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"TI Scoreboard" in response.data


def test_games_endpoint_is_empty_and_warming_before_any_poll(client):
    data = client.get("/api/games").get_json()

    assert data["games"] == []
    assert data["warming_up"] is True
    assert data["poll"]["stale"] is True


def test_games_endpoint_returns_seeded_snapshot(app, client, payload):
    seed(app, delay_ago=200, payload=payload)

    data = client.get("/api/games?delay=120").get_json()

    assert data["warming_up"] is False
    assert len(data["games"]) == 3
    assert data["games"][0]["radiant"]["name"] == "Team Spirit"
    assert data["games"][0]["clock"] == "35:15"
    assert data["delay_seconds"] == 120.0


def test_delay_is_honoured_and_hides_newer_snapshots(app, client, payload):
    """The point of the whole system: a fresh snapshot must not leak through."""
    buffer = app.config["buffer"]
    old = parse_live_games(payload, league_id=TI_LEAGUE_ID)
    buffer.append(old, timestamp=time.time() - 300)

    spoiler = json.loads(FIXTURE.read_text(encoding="utf-8"))
    spoiler["result"]["games"][0]["scoreboard"]["radiant"]["score"] = 999
    buffer.append(parse_live_games(spoiler, league_id=TI_LEAGUE_ID), timestamp=time.time())

    data = client.get("/api/games?delay=120").get_json()

    assert data["games"][0]["radiant"]["score"] == 23, "the 999 snapshot leaked through"


def test_zero_delay_shows_the_newest_snapshot(app, client, payload):
    seed(app, delay_ago=0, payload=payload)

    data = client.get("/api/games?delay=0").get_json()
    assert len(data["games"]) == 3


def test_delay_is_clamped_to_retention(app, client, payload):
    seed(app, delay_ago=0, payload=payload)

    data = client.get("/api/games?delay=99999").get_json()

    assert data["delay_seconds"] == 900.0
    assert "error" not in data


def test_negative_delay_is_clamped_not_rejected(app, client, payload):
    seed(app, delay_ago=0, payload=payload)
    assert client.get("/api/games?delay=-50").get_json()["delay_seconds"] == 0.0


def test_non_numeric_delay_is_a_400(client):
    response = client.get("/api/games?delay=soon")
    assert response.status_code == 400


def test_suggested_delay_comes_from_valves_reported_stream_delay(app, client, payload):
    seed(app, delay_ago=200, payload=payload)

    assert client.get("/api/games").get_json()["suggested_delay"] == 120


def test_suggested_delay_takes_the_largest_across_games(app, client, payload):
    """Erring older is harmless; erring newer spoils fights."""
    payload["result"]["games"][0]["stream_delay_s"] = 300
    seed(app, delay_ago=200, payload=payload)

    assert client.get("/api/games").get_json()["suggested_delay"] == 300


def test_suggested_delay_is_null_when_valve_does_not_say(app, client, payload):
    for game in payload["result"]["games"]:
        game.pop("stream_delay_s", None)
    seed(app, delay_ago=200, payload=payload)

    assert client.get("/api/games").get_json()["suggested_delay"] is None


def test_zero_stream_delay_is_ignored_rather_than_trusted(app, client, payload):
    """A reported 0 would disable the spoiler guard entirely; fall back instead."""
    for game in payload["result"]["games"]:
        game["stream_delay_s"] = 0
    seed(app, delay_ago=200, payload=payload)

    assert client.get("/api/games").get_json()["suggested_delay"] is None


# ---- viewer selection ---------------------------------------------------
# The one piece of server state: which stream the main screen is showing. It
# has to live here because it passes between two browsers on two screens.


@pytest.fixture
def viewer_app(config, payload):
    """An app with a known stream list, so the tests don't depend on the real
    streams.toml, whose video IDs change every day of the event."""
    app = create_app(
        config,
        source=StubSource(payload=payload),
        heroes=HeroIndex({}),
        start_poller=False,
        streams=[
            Stream(index=0, kind="youtube", id="aaa", label="https://youtu.be/aaa"),
            Stream(index=1, kind="youtube", id="bbb", label="https://youtu.be/bbb"),
            Stream(index=2, kind="twitch", id="dota2ti_3", label="twitch.tv/dota2ti_3"),
            Stream(index=3, kind="empty", id="", label="no stream configured"),
        ],
    )
    return app


@pytest.fixture
def viewer_client(viewer_app):
    return viewer_app.test_client()


def test_viewer_starts_with_nothing_selected(viewer_client):
    data = viewer_client.get("/api/viewer").get_json()

    assert data["selected"] is None
    assert data["count"] == 4


def test_viewer_exposes_the_resolved_stream_list(viewer_client):
    streams = viewer_client.get("/api/viewer").get_json()["streams"]

    assert streams[0] == {"index": 0, "kind": "youtube", "id": "aaa",
                          "label": "https://youtu.be/aaa", "title": ""}
    assert streams[3]["kind"] == "empty"


def test_selecting_a_stream_is_reported_back_to_the_viewer(viewer_client):
    assert viewer_client.post("/api/viewer/select/2").get_json()["selected"] == 2

    assert viewer_client.get("/api/viewer").get_json()["selected"] == 2


def test_an_out_of_range_selection_is_a_400(viewer_client):
    assert viewer_client.post("/api/viewer/select/9").status_code == 400


def test_a_rejected_selection_leaves_the_previous_one_showing(viewer_client):
    """A bad click must not blank the main screen mid-game."""
    viewer_client.post("/api/viewer/select/1")

    viewer_client.post("/api/viewer/select/9")

    assert viewer_client.get("/api/viewer").get_json()["selected"] == 1


def test_an_empty_slot_can_still_be_selected(viewer_client):
    """The viewer shows a labelled placeholder; rejecting it here would make an
    unconfigured stream look like a broken scoreboard instead."""
    assert viewer_client.post("/api/viewer/select/3").status_code == 200


def test_selecting_streams_does_not_disturb_the_scores(viewer_app, viewer_client, payload):
    """The scores are the part that must never break."""
    seed(viewer_app, delay_ago=0, payload=payload)

    viewer_client.post("/api/viewer/select/2")

    assert len(viewer_client.get("/api/games?delay=0").get_json()["games"]) == 3


def test_viewer_page_is_served(viewer_client):
    response = viewer_client.get("/viewer")

    assert response.status_code == 200
    assert b"viewer.js" in response.data


def test_heroes_endpoint_exposes_icons(client):
    data = client.get("/api/heroes").get_json()

    assert data["1"]["name"] == "antimage"
    assert data["1"]["icon"].endswith("/antimage.png")


def test_poll_failure_keeps_serving_the_last_good_snapshot(app, client, payload):
    """Valve's API falls over during TI. The screen must not go blank."""
    seed(app, delay_ago=200, payload=payload)

    poller = app.config["poller"]
    app.config["stub_source"].error = SourceError("503 from Valve")
    poller._source = app.config["stub_source"]
    with pytest.raises(SourceError):
        poller.poll_once()
    poller.last_error = "503 from Valve"

    data = client.get("/api/games?delay=120").get_json()

    assert len(data["games"]) == 3, "lost the last good snapshot on a poll failure"
    assert data["poll"]["last_error"] == "503 from Valve"


def test_poll_once_populates_the_buffer(app, client):
    app.config["poller"].poll_once()

    data = client.get("/api/games?delay=0").get_json()
    assert len(data["games"]) == 3
    assert data["poll"]["stale"] is False


# ---- reloading the stream list -----------------------------------------
# The morning routine is "paste today's video ids into streams.toml". Without
# this it also means restarting the server and reloading the viewer, which is
# two more things to remember while a match is starting.


def test_reload_picks_up_a_changed_stream_list(viewer_app, viewer_client, monkeypatch):
    import scoreboard.server as server_module

    monkeypatch.setattr(server_module, "load_streams", lambda: [
        Stream(index=0, kind="youtube", id="new0", label="https://youtu.be/new0"),
        Stream(index=1, kind="youtube", id="new1", label="https://youtu.be/new1"),
    ])

    data = viewer_client.post("/api/viewer/reload").get_json()

    assert data["count"] == 2
    assert data["streams"][0]["id"] == "new0"
    assert viewer_client.get("/api/viewer").get_json()["streams"][0]["id"] == "new0"


def test_reload_keeps_a_selection_that_still_exists(viewer_app, viewer_client, monkeypatch):
    import scoreboard.server as server_module
    viewer_client.post("/api/viewer/select/1")

    monkeypatch.setattr(server_module, "load_streams", lambda: [
        Stream(index=i, kind="youtube", id=f"n{i}", label=f"https://youtu.be/n{i}")
        for i in range(4)
    ])
    viewer_client.post("/api/viewer/reload")

    assert viewer_client.get("/api/viewer").get_json()["selected"] == 1


def test_reload_drops_a_selection_that_no_longer_exists(viewer_app, viewer_client, monkeypatch):
    """Four streams down to two must not leave the viewer pointing at slot 4."""
    import scoreboard.server as server_module
    viewer_client.post("/api/viewer/select/3")

    monkeypatch.setattr(server_module, "load_streams", lambda: [
        Stream(index=0, kind="youtube", id="a", label="a"),
        Stream(index=1, kind="youtube", id="b", label="b"),
    ])
    viewer_client.post("/api/viewer/reload")

    assert viewer_client.get("/api/viewer").get_json()["selected"] == 0


def test_selection_is_validated_against_the_reloaded_list(viewer_app, viewer_client, monkeypatch):
    import scoreboard.server as server_module

    monkeypatch.setattr(server_module, "load_streams", lambda: [
        Stream(index=0, kind="youtube", id="a", label="a"),
        Stream(index=1, kind="youtube", id="b", label="b"),
    ])
    viewer_client.post("/api/viewer/reload")

    assert viewer_client.post("/api/viewer/select/3").status_code == 400
    assert viewer_client.post("/api/viewer/select/1").status_code == 200


# ---- smoke detection ----------------------------------------------------
# Valve publishes no buff data, so "they smoked" cannot be read directly. What
# CAN be read is Smoke of Deceit leaving a team's inventory, which is what using
# it does. Comparing the served snapshot against an OLDER one detects that --
# and it must be older, never newer, or the check would be reading the future
# and spoiling the very thing it announces.

SMOKE = 188


def game_payload(match_id, smokes_radiant, clock=600):
    def player(items):
        slots = {f"item{i}": (items[i] if i < len(items) else 0) for i in range(6)}
        return {"hero_id": 1, "net_worth": 100, **slots}

    return {"result": {"games": [{
        "match_id": match_id, "league_id": TI_LEAGUE_ID, "spectators": 0,
        "radiant_team": {"team_name": "R"}, "dire_team": {"team_name": "D"},
        "scoreboard": {
            "duration": clock,
            "radiant": {"score": 1, "players": [player([SMOKE] * smokes_radiant)]},
            "dire": {"score": 2, "players": [player([])]},
        },
    }]}}


def seed_at(app, payload, age):
    app.config["buffer"].append(
        parse_live_games(payload, league_id=TI_LEAGUE_ID), timestamp=time.time() - age)


def test_a_smoke_leaving_the_inventory_is_reported(app, client):
    seed_at(app, game_payload(1, smokes_radiant=1), age=200)
    seed_at(app, game_payload(1, smokes_radiant=0), age=120)

    game = client.get("/api/games?delay=120").get_json()["games"][0]

    assert game["radiant"]["smoked"] is True
    assert game["dire"]["smoked"] is False


def test_carrying_a_smoke_without_using_it_is_not_reported(app, client):
    seed_at(app, game_payload(1, smokes_radiant=1), age=200)
    seed_at(app, game_payload(1, smokes_radiant=1), age=120)

    game = client.get("/api/games?delay=120").get_json()["games"][0]

    assert game["radiant"]["smoked"] is False


def test_buying_a_smoke_is_not_reported(app, client):
    seed_at(app, game_payload(1, smokes_radiant=0), age=200)
    seed_at(app, game_payload(1, smokes_radiant=1), age=120)

    assert client.get("/api/games?delay=120").get_json()["games"][0]["radiant"]["smoked"] is False


def test_detection_never_reads_newer_than_the_delay_allows(app, client):
    """The comparison window must sit BEHIND the served snapshot.

    A smoke used after the moment being shown is a fight that has not happened
    on screen yet -- announcing it is exactly the spoiler this project exists to
    prevent.
    """
    seed_at(app, game_payload(1, smokes_radiant=1), age=200)
    seed_at(app, game_payload(1, smokes_radiant=1), age=130)
    seed_at(app, game_payload(1, smokes_radiant=0), age=5)   # the future, at delay=120

    assert client.get("/api/games?delay=120").get_json()["games"][0]["radiant"]["smoked"] is False


def test_no_history_yet_reports_no_smoke(app, client):
    seed_at(app, game_payload(1, smokes_radiant=0), age=120)

    assert client.get("/api/games?delay=120").get_json()["games"][0]["radiant"]["smoked"] is False


def test_smoke_lookback_never_exceeds_retention(app, client):
    """At maximum delay there is no room to look further back.

    The buffer refuses a lookback past its retention, and that refusal used to
    take the whole /api/games response down with it -- losing the scores to
    decorate them.
    """
    seed_at(app, game_payload(1, smokes_radiant=1), age=200)

    response = client.get("/api/games?delay=99999")

    assert response.status_code == 200
    assert response.get_json()["delay_seconds"] == 900.0


def test_a_smoke_bought_and_used_inside_the_window_is_still_caught(app, client):
    """The case that was being missed.

    Comparing only the two ends of the window reads zero smokes at both, because
    the team bought one and used it in between -- which is exactly what teams do
    with smokes, and why they seemed impossible to catch.
    """
    # Both edges of the window read zero: the buy and the use happen strictly
    # between them, which is the whole point of the case.
    seed_at(app, game_payload(1, smokes_radiant=0), age=200)
    seed_at(app, game_payload(1, smokes_radiant=0), age=160)   # window edge: none
    seed_at(app, game_payload(1, smokes_radiant=1), age=150)   # bought
    seed_at(app, game_payload(1, smokes_radiant=0), age=135)   # used
    seed_at(app, game_payload(1, smokes_radiant=0), age=120)   # served: none

    assert client.get("/api/games?delay=120").get_json()["games"][0]["radiant"]["smoked"] is True


def test_a_steady_zero_across_the_window_is_not_a_smoke(app, client):
    for age in (200, 160, 140, 120):
        seed_at(app, game_payload(1, smokes_radiant=0), age=age)

    assert client.get("/api/games?delay=120").get_json()["games"][0]["radiant"]["smoked"] is False


def test_buying_without_using_inside_the_window_is_not_a_smoke(app, client):
    seed_at(app, game_payload(1, smokes_radiant=0), age=200)
    seed_at(app, game_payload(1, smokes_radiant=1), age=160)
    seed_at(app, game_payload(1, smokes_radiant=1), age=120)

    assert client.get("/api/games?delay=120").get_json()["games"][0]["radiant"]["smoked"] is False
