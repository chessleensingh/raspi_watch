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
