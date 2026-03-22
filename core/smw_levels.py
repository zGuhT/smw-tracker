"""
Per-ROM level ID to name mapping.

The JSON file is keyed by ROM name (game_name as derived from the ROM filename),
so level slot 0x38 can mean different things in different hacks.

Format of smw_levels.json:
{
  "Sweet Shell": {
    "38": "Shrimple",
    "34": "Gromethian",
    ...
  },
  "Love Yourself 1.0": {
    "42": "First Steps",
    ...
  }
}
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LEVELS_PATH = BASE_DIR / "data" / "smw_levels.json"


def normalize_level_id(level_id: str | None) -> str | None:
    if level_id is None:
        return None
    cleaned = str(level_id).strip().upper()
    if cleaned.startswith("0X"):
        cleaned = cleaned[2:]
    return cleaned


@lru_cache(maxsize=1)
def _load_all_level_maps() -> dict[str, dict[str, str]]:
    """Load the entire ROM-keyed level map file."""
    if not LEVELS_PATH.exists():
        return {}
    with LEVELS_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    # Normalize all level IDs within each ROM entry
    result: dict[str, dict[str, str]] = {}
    for rom_name, levels in raw.items():
        if isinstance(levels, dict):
            result[rom_name] = {
                normalize_level_id(k): v for k, v in levels.items()
            }
    return result


def get_level_map_for_rom(game_name: str | None) -> dict[str, str]:
    """Return the level ID->name mapping for a specific ROM, or empty dict."""
    if not game_name:
        return {}
    all_maps = _load_all_level_maps()
    return all_maps.get(game_name, {})


def get_level_name(level_id: str | None, game_name: str | None = None) -> str | None:
    """
    Look up a level name by ID, scoped to the current ROM.

    If game_name is provided, only returns names from that ROM's mapping.
    If game_name is None, returns None (no global fallback — avoids cross-hack contamination).
    """
    normalized = normalize_level_id(level_id)
    if normalized is None:
        return None

    level_map = get_level_map_for_rom(game_name)
    return level_map.get(normalized)


def reload_levels() -> None:
    """Clear the cache so the file is re-read on next access."""
    _load_all_level_maps.cache_clear()
