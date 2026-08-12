"""Config loading.

The Steam API key can come from the environment instead of the file, so the key
never has to be written to disk if you'd rather not.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent.parent / "config.toml"


@dataclass(frozen=True)
class Config:
    steam_api_key: str
    league_id: int | None
    """None means "show every live league game" - useful before you've looked up
    TI's id with scripts/find_league.py."""
    poll_interval_seconds: float
    default_delay_seconds: float
    retention_seconds: float
    host: str
    port: int
    wall_url: str
    """Base URL of the wall's remote control on the Mac, e.g.
    http://macbook-pro:8777. Empty disables tile-click stream switching."""

    def require_key(self) -> str:
        if not self.steam_api_key:
            raise SystemExit(
                "No Steam API key. Get one free at https://steamcommunity.com/dev/apikey\n"
                "then either set STEAM_API_KEY in your environment or put it in "
                f"{DEFAULT_PATH} under [steam] api_key."
            )
        return self.steam_api_key


def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_PATH
    # utf-8-sig: editors on Windows write a BOM, which tomllib rejects outright.
    data = tomllib.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}

    steam = data.get("steam", {})
    scoreboard = data.get("scoreboard", {})
    server = data.get("server", {})

    league_id = scoreboard.get("league_id")
    # 0 is a convenient "unset" marker in TOML, since a bare key can't be null.
    if league_id in (0, ""):
        league_id = None

    retention = float(scoreboard.get("retention_seconds", 900.0))
    default_delay = float(scoreboard.get("default_delay_seconds", 120.0))
    if default_delay > retention:
        raise SystemExit(
            f"default_delay_seconds ({default_delay}) exceeds retention_seconds "
            f"({retention}); the buffer would evict the snapshot it needs."
        )

    return Config(
        steam_api_key=os.environ.get("STEAM_API_KEY") or steam.get("api_key", ""),
        league_id=league_id,
        poll_interval_seconds=float(scoreboard.get("poll_interval_seconds", 15.0)),
        default_delay_seconds=default_delay,
        retention_seconds=retention,
        host=server.get("host", "0.0.0.0"),
        port=int(server.get("port", 8000)),
        wall_url=(data.get("wall", {}).get("url", "") or "").rstrip("/"),
    )
