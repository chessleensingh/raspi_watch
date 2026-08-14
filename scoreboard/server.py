"""Flask app + background poller.

The poller writes snapshots into the DelayBuffer on its own cadence; requests read
whatever the buffer says the world looked like `delay` seconds ago. The two are
decoupled on purpose, so you can retune the delay mid-game without touching polling.

The delay is a per-request query parameter rather than server state. That keeps the
server stateless, lets the small screen and a phone run different delays, and makes
the client's localStorage the single source of truth for the setting.

The viewer selection is the one deliberate exception. The delay is per-client *by
design* - the table screen and a phone may legitimately want different offsets -
whereas the selection is inherently a single shared value travelling from the
scoreboard on the small screen to the viewer on the main screen. There is nowhere
else for it to live.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from scoreboard.config import Config, load_config
from scoreboard.delay import DelayBuffer
from scoreboard.demo import DemoSource
from scoreboard.heroes import HeroIndex
from scoreboard.models import parse_live_games
from scoreboard.source import SourceError, ValveSource
from scoreboard.streams import Stream, load_streams

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
MAX_BACKOFF_SECONDS = 120.0


class Poller(threading.Thread):
    """Fetches live games on an interval and files them into the buffer."""

    def __init__(self, source, buffer: DelayBuffer, config: Config) -> None:
        super().__init__(name="poller", daemon=True)
        self._source = source
        self._buffer = buffer
        self._config = config
        self._stop = threading.Event()

        self.last_success: float | None = None
        self.last_error: str | None = None
        self.consecutive_failures = 0

    def stop(self) -> None:
        self._stop.set()

    def poll_once(self) -> None:
        payload = self._source.fetch_live_games()
        games = parse_live_games(payload, league_id=self._config.league_id)
        self._buffer.append(games, timestamp=time.time())
        self.last_success = time.time()
        self.last_error = None
        self.consecutive_failures = 0

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
                wait = self._config.poll_interval_seconds
            except SourceError as exc:
                # Never fatal. The buffer keeps serving the last good snapshot and
                # the UI flags it as stale, which beats blanking the screen.
                self.consecutive_failures += 1
                self.last_error = str(exc)
                wait = min(
                    self._config.poll_interval_seconds * 2**self.consecutive_failures,
                    MAX_BACKOFF_SECONDS,
                )
                log.warning("poll failed (%d in a row), retrying in %.0fs: %s",
                            self.consecutive_failures, wait, exc)
            except Exception:
                self.consecutive_failures += 1
                self.last_error = "unexpected poller error"
                wait = MAX_BACKOFF_SECONDS
                log.exception("unexpected error in poller")

            self._stop.wait(wait)


# How far back to look for a smoke that has since been used. Smoke of Deceit
# lasts 35 seconds, so a window near that lights the tile for roughly as long as
# the smoke is actually up.
SMOKE_WINDOW_SECONDS = 40.0


def smoked_sides(games, buffer, delay_seconds: float, now: float) -> dict:
    """match_id -> {"radiant": bool, "dire": bool} for smokes just used.

    Returned rather than stamped onto the games: Game is frozen, and keeping
    this out of the model is right anyway -- whether a smoke was used is a fact
    about two snapshots, not about either one of them.

    The comparison snapshot is taken FURTHER BACK than the one being served,
    never nearer to now. Looking forward would announce a gank that has not
    happened on your screen yet, which is precisely the spoiler this project
    exists to prevent -- while calling itself a feature.
    """
    result = {g.match_id: {"radiant": False, "dire": False} for g in games}

    # At the maximum delay there is no room to look further back -- the buffer
    # refuses a lookback past its retention, since that snapshot is already
    # evicted. Losing the smoke flag is the right trade: the delay itself is the
    # feature this must never break.
    lookback = min(delay_seconds + SMOKE_WINDOW_SECONDS, buffer.retention_seconds)
    if lookback <= delay_seconds:
        return result

    older = buffer.get_delayed(delay_seconds=lookback, now=now)
    if older.warming_up:
        return result

    before = {g.match_id: g for g in older.games}
    for game in games:
        was = before.get(game.match_id)
        if not was:
            continue
        result[game.match_id] = {
            "radiant": game.radiant.smoke_count < was.radiant.smoke_count,
            "dire": game.dire.smoke_count < was.dire.smoke_count,
        }
    return result


def create_app(config: Config, source=None, heroes: HeroIndex | None = None,
               start_poller: bool = True, streams: list[Stream] | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)

    source = source or ValveSource(config.require_key())
    heroes = heroes if heroes is not None else HeroIndex.load(source)
    streams = streams if streams is not None else load_streams()
    buffer = DelayBuffer(retention_seconds=config.retention_seconds)
    poller = Poller(source, buffer, config)

    app.config["buffer"] = buffer
    app.config["poller"] = poller
    app.config["heroes"] = heroes
    app.config["app_config"] = config
    app.config["streams"] = streams
    # None until the first click. The viewer shows stream 0 in the meantime.
    app.config["selected_stream"] = None

    if start_poller:
        poller.start()

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/static/<path:filename>")
    def static_files(filename):
        return send_from_directory(STATIC_DIR, filename)

    @app.get("/api/heroes")
    def api_heroes():
        return jsonify(heroes.to_dict())

    # ---- viewer selection ----------------------------------------------
    # Which stream the main screen is showing. The scoreboard POSTs it, the
    # viewer polls it. See the module docstring for why this is server state
    # when the delay deliberately is not.

    @app.get("/viewer")
    def viewer():
        return send_from_directory(STATIC_DIR, "viewer.html")

    def viewer_state():
        """Always read the CURRENT list. Capturing it in a closure would make
        /api/viewer/reload a no-op for every endpoint but itself."""
        current = app.config["streams"]
        return {
            "selected": app.config["selected_stream"],
            "count": len(current),
            "streams": [s.to_dict() for s in current],
        }

    @app.get("/api/viewer")
    def api_viewer():
        return jsonify(viewer_state())

    @app.post("/api/viewer/reload")
    def api_viewer_reload():
        """Re-read streams.toml without restarting.

        The morning routine is pasting the day's video ids into that file, and
        making that also mean "restart the server, then reload the viewer" is
        two things to remember while a match is starting."""
        app.config["streams"] = load_streams()

        # A list that shrank must not leave the selection pointing past its end.
        selected = app.config["selected_stream"]
        if selected is not None and selected >= len(app.config["streams"]):
            app.config["selected_stream"] = 0 if app.config["streams"] else None

        log.info("reloaded %d stream(s) from disk", len(app.config["streams"]))
        return jsonify(viewer_state())

    @app.post("/api/viewer/select/<int:index>")
    def api_viewer_select(index: int):
        if not 0 <= index < len(app.config["streams"]):
            # Leave the previous selection alone: a bad click must not blank
            # the main screen mid-game.
            return jsonify({
                "error": f"no stream {index}; "
                         f"{len(app.config['streams'])} configured",
                "selected": app.config["selected_stream"],
            }), 400

        # One atomic rebind, so no lock is needed. A lost race costs one poll.
        app.config["selected_stream"] = index
        return jsonify({"selected": index})

    @app.get("/api/games")
    def api_games():
        try:
            delay = float(request.args.get("delay", config.default_delay_seconds))
        except ValueError:
            return jsonify({"error": "delay must be a number"}), 400

        delay = max(0.0, min(delay, config.retention_seconds))
        now = time.time()
        result = buffer.get_delayed(delay_seconds=delay, now=now)
        smoked = smoked_sides(result.games, buffer, delay, now)

        last_success_age = (
            time.time() - poller.last_success if poller.last_success else None
        )

        # Valve reports the broadcast delay per game. Take the largest: showing
        # data older than necessary is harmless, showing it too early is the one
        # thing this whole system exists to prevent. None when no game says.
        reported = [g.stream_delay for g in result.games if g.stream_delay]
        suggested_delay = max(reported) if reported else None

        def with_smoke(game):
            data = game.to_dict()
            flags = smoked.get(game.match_id, {})
            data["radiant"]["smoked"] = flags.get("radiant", False)
            data["dire"]["smoked"] = flags.get("dire", False)
            return data

        return jsonify({
            "games": [with_smoke(g) for g in result.games],
            "delay_seconds": delay,
            "suggested_delay": suggested_delay,
            "warming_up": result.warming_up,
            "snapshot_age": result.snapshot_age,
            "league_id": config.league_id,
            "poll": {
                "last_success_age": last_success_age,
                "last_error": poller.last_error,
                "consecutive_failures": poller.consecutive_failures,
                # Two missed polls is enough to call it stale without flapping.
                "stale": last_success_age is None
                or last_success_age > config.poll_interval_seconds * 3,
            },
        })

    return app


def prewarm(app, source, config, span_seconds: float = 600.0, step: float = 15.0) -> None:
    """Backfill the buffer with backdated snapshots.

    Without this a fresh server shows "warming up" and an empty board until it
    has accumulated `delay` seconds of history -- two minutes of nothing, which
    makes demo mode useless for the thing it exists for. Backdating costs
    nothing because the source can answer for any moment.
    """
    buffer = app.config["buffer"]
    now = time.time()
    # Ask the source what the world looked like AT each backdated moment, not
    # what it looks like now. Identical history detects no change, and the smoke
    # haze fires on a change -- so without this the demo cannot show it.
    at_moment = getattr(source, "payload_at", None)
    for age in range(int(span_seconds), 0, -int(step)):
        moment = now - age
        payload = at_moment(moment) if at_moment else source.fetch_live_games()
        buffer.append(parse_live_games(payload, league_id=config.league_id),
                      timestamp=moment)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    config = load_config()

    demo = "--demo" in sys.argv
    if demo:
        # Stand-in games, for when Valve is publishing none. See scoreboard/demo.py.
        source = DemoSource(league_id=config.league_id)
        # The poller is held back until the backdated history is in: the buffer
        # rejects out-of-order timestamps, and a live snapshot landing first
        # would make every backdated one look like time running backwards.
        app = create_app(config, source=source, heroes=HeroIndex.load(source),
                         start_poller=False)
        prewarm(app, source, config)
        app.config["poller"].start()
        log.warning("DEMO MODE - the games on screen are invented, not live")
    else:
        source = None
        app = create_app(config)

    if config.league_id is None and not demo:
        log.warning(
            "No league_id set - showing every live league game. Run "
            "`python scripts/find_league.py` during TI to find its id."
        )

    log.info("scoreboard on http://%s:%d  (delay %.0fs)",
             config.host, config.port, config.default_delay_seconds)
    app.run(host=config.host, port=config.port, threaded=True)


if __name__ == "__main__":
    main()
