"""Valve Web API client.

Deliberately thin: it fetches and hands back raw dicts. `models.parse_live_games`
does the interpreting. That split is what makes an OpenDota fallback cheap to add
if Valve's API gets flaky mid-tournament, which it has a history of doing.
"""

from __future__ import annotations

import logging

import requests

LIVE_GAMES_URL = "https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/"
HEROES_URL = "https://api.steampowered.com/IEconDOTA2_570/GetHeroes/v1/"

log = logging.getLogger(__name__)


class SourceError(RuntimeError):
    """Any failure to get usable data. Callers keep serving the last good snapshot."""


class ValveSource:
    def __init__(self, api_key: str, timeout: float = 10.0) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._session = requests.Session()

    def _get(self, url: str, **params) -> dict:
        params["key"] = self._api_key
        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            raise SourceError(f"request to {url} failed: {exc}") from exc

        if response.status_code == 403:
            raise SourceError("Steam API rejected the key (403). Check STEAM_API_KEY.")
        if response.status_code != 200:
            raise SourceError(f"{url} returned HTTP {response.status_code}")

        try:
            return response.json()
        except ValueError as exc:
            # Valve serves an HTML error page under load rather than JSON.
            raise SourceError(f"{url} returned non-JSON ({len(response.content)}B)") from exc

    def fetch_live_games(self) -> dict:
        return self._get(LIVE_GAMES_URL)

    def fetch_heroes(self) -> dict:
        return self._get(HEROES_URL, language="en_us")
