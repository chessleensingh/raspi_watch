"""Flask app + background poller.

The poller writes snapshots into the DelayBuffer on its own cadence; requests read
whatever the buffer says the world looked like `delay` seconds ago. The two are
decoupled on purpose, so you can retune the delay mid-game without touching polling.

The delay is a per-request query parameter rather than server state. That keeps the
server stateless, lets the small screen and a phone run different delays, and makes
the client's localStorage the single source of truth for the setting.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory

from scoreboard.config import Config, load_config
from scoreboard.delay import DelayBuffer
from scoreboard.heroes import HeroIndex
from scoreboard.models import parse_live_games
from scoreboard.source import SourceError, ValveSource

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


def create_app(config: Config, source=None, heroes: HeroIndex | None = None,
               start_poller: bool = True) -> Flask:
    app = Flask(__name__, static_folder=None)

    source = source or ValveSource(config.require_key())
    heroes = heroes if heroes is not None else HeroIndex.load(source)
    buffer = DelayBuffer(retention_seconds=config.retention_seconds)
    poller = Poller(source, buffer, config)

    app.config["buffer"] = buffer
    app.config["poller"] = poller
    app.config["heroes"] = heroes
    app.config["app_config"] = config

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

    # ---- wall remote control -------------------------------------------
    # Proxied rather than called from the browser: it keeps the Mac's address
    # in one config file, avoids CORS, and means the page works even where the
    # browser cannot resolve the Mac's tailnet name.

    @app.get("/api/wall")
    def api_wall_status():
        if not config.wall_url:
            return jsonify({"enabled": False})
        try:
            response = requests.get(f"{config.wall_url}/status", timeout=3)
            return jsonify({"enabled": True, **response.json()})
        except (requests.RequestException, ValueError) as exc:
            return jsonify({"enabled": True, "error": str(exc)}), 502

    @app.post("/api/wall/audio/<int:tile>")
    def api_wall_audio(tile: int):
        if not config.wall_url:
            return jsonify({"error": "no wall configured; set [wall] url"}), 503
        try:
            response = requests.post(f"{config.wall_url}/audio/{tile}", timeout=3)
            return jsonify(response.json()), response.status_code
        except (requests.RequestException, ValueError) as exc:
            # The wall being down must never break the scoreboard.
            log.warning("wall control failed: %s", exc)
            return jsonify({"error": f"wall unreachable: {exc}"}), 502

    @app.get("/api/games")
    def api_games():
        try:
            delay = float(request.args.get("delay", config.default_delay_seconds))
        except ValueError:
            return jsonify({"error": "delay must be a number"}), 400

        delay = max(0.0, min(delay, config.retention_seconds))
        result = buffer.get_delayed(delay_seconds=delay, now=time.time())

        last_success_age = (
            time.time() - poller.last_success if poller.last_success else None
        )

        # Valve reports the broadcast delay per game. Take the largest: showing
        # data older than necessary is harmless, showing it too early is the one
        # thing this whole system exists to prevent. None when no game says.
        reported = [g.stream_delay for g in result.games if g.stream_delay]
        suggested_delay = max(reported) if reported else None

        return jsonify({
            "games": [g.to_dict() for g in result.games],
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


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    config = load_config()
    app = create_app(config)

    if config.league_id is None:
        log.warning(
            "No league_id set - showing every live league game. Run "
            "`python scripts/find_league.py` during TI to find its id."
        )

    log.info("scoreboard on http://%s:%d  (delay %.0fs)",
             config.host, config.port, config.default_delay_seconds)
    app.run(host=config.host, port=config.port, threaded=True)


if __name__ == "__main__":
    main()
