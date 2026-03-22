"""
Resolve level IDs to human-readable names.

Priority:
1. game_levels table (user-defined names from setup page)
2. smw_levels.json (per-ROM hardcoded names)
3. Abbreviated game name + level ID fallback
"""
from __future__ import annotations

from core import db
from core.smw_levels import get_level_name as get_json_level_name


def _abbreviate_game_name(game_name: str) -> str:
    """Generate a short abbreviation: 'Quickie World 2' -> 'QW2', 'Sweet Shell' -> 'SS'"""
    words = game_name.replace("-", " ").replace("_", " ").split()
    if len(words) == 1:
        return words[0][:3].upper()
    abbrev = ""
    for w in words:
        if w[0].isdigit():
            abbrev += w  # Keep numbers as-is
        else:
            abbrev += w[0].upper()
    return abbrev or game_name[:3].upper()


def resolve_level_name(level_id: str | None, game_name: str | None = None) -> str:
    """
    Get a display name for a level_id.
    Checks game_levels DB first, then smw_levels.json, then falls back to abbreviation.
    """
    if not level_id:
        return "Unknown"

    # Strip secret suffix for lookup
    base_id = level_id.split(":")[0] if ":" in level_id else level_id
    is_secret = ":secret" in level_id

    # 1. Check game_levels table
    if game_name:
        row = db.fetchone(
            "SELECT level_name FROM game_levels WHERE game_name = ? AND level_id = ? LIMIT 1",
            (game_name, base_id),
        )
        if row and row["level_name"]:
            name = row["level_name"]
            return f"{name} (Secret)" if is_secret else name

    # 2. Check smw_levels.json
    if game_name:
        json_name = get_json_level_name(base_id, game_name=game_name)
        if json_name:
            return f"{json_name} (Secret)" if is_secret else json_name

    # 3. Fallback: abbreviation + ID
    if game_name:
        abbrev = _abbreviate_game_name(game_name)
        label = f"{abbrev}_{base_id}"
    else:
        label = base_id

    return f"{label} (Secret)" if is_secret else label


def resolve_split_names(splits: list[dict], game_name: str | None = None) -> list[dict]:
    """Add resolved level_name to a list of split dicts."""
    for s in splits:
        lid = s.get("level_id")
        existing_name = s.get("level_name")
        # Only resolve if name is missing or is just the raw ID
        if not existing_name or existing_name == lid:
            s["level_name"] = resolve_level_name(lid, game_name)
    return splits
