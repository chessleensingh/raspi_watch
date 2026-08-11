"""hero_id -> display name and icon URL, cached to disk.

Hero ids are stable, so this is fetched once and reused. The cache also means the
draft still renders if Valve's API is down when the server starts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

CACHE_PATH = Path(__file__).parent / ".hero_cache.json"
ICON_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes"

log = logging.getLogger(__name__)


def _short_name(api_name: str) -> str:
    """`npc_dota_hero_queenofpain` -> `queenofpain`, which is what the CDN uses."""
    return api_name.removeprefix("npc_dota_hero_")


class HeroIndex:
    def __init__(self, mapping: dict[int, str] | None = None) -> None:
        self._by_id = mapping or {}

    def __len__(self) -> int:
        return len(self._by_id)

    def name(self, hero_id: int) -> str:
        return self._by_id.get(hero_id, f"hero_{hero_id}")

    def icon_url(self, hero_id: int) -> str:
        return f"{ICON_BASE}/{self.name(hero_id)}.png"

    def to_dict(self) -> dict[str, dict[str, str]]:
        """Shipped to the browser once so the page can render drafts client-side."""
        return {
            str(hero_id): {"name": name, "icon": f"{ICON_BASE}/{name}.png"}
            for hero_id, name in self._by_id.items()
        }

    @classmethod
    def load(cls, source=None, cache_path: Path = CACHE_PATH) -> "HeroIndex":
        """Cache first, network second, empty last.

        An empty index is survivable: the draft toggle just shows placeholder names.
        Nothing else on the scoreboard depends on it.
        """
        if cache_path.exists():
            try:
                raw = json.loads(cache_path.read_text(encoding="utf-8"))
                return cls({int(k): v for k, v in raw.items()})
            except (ValueError, OSError) as exc:
                log.warning("hero cache unreadable, refetching: %s", exc)

        if source is None:
            return cls()

        try:
            payload = source.fetch_heroes()
        except Exception as exc:
            log.warning("could not fetch heroes, drafts will show placeholders: %s", exc)
            return cls()

        mapping = {
            h["id"]: _short_name(h.get("name", ""))
            for h in payload.get("result", {}).get("heroes", [])
            if "id" in h
        }
        if mapping:
            try:
                cache_path.write_text(json.dumps(mapping), encoding="utf-8")
            except OSError as exc:
                log.warning("could not write hero cache: %s", exc)

        return cls(mapping)
