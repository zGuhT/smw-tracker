"""Export and import game levels and run definitions as JSON."""
from __future__ import annotations

import json
from typing import Any

from core import db
from core.level_service import create_level, get_levels_for_game
from core.run_service import create_run, get_runs_for_game, get_run_levels, set_run_levels
from core.time_utils import utc_now_iso


def export_game_config(game_name: str) -> dict[str, Any]:
    """Export all levels and runs for a game as a JSON-serializable dict."""
    levels = get_levels_for_game(game_name)
    runs = get_runs_for_game(game_name)

    run_configs = []
    for run in runs:
        run_levels = get_run_levels(run["id"])
        run_configs.append({
            "run_name": run["run_name"],
            "is_default": bool(run["is_default"]),
            "start_delay_ms": run["start_delay_ms"],
            "levels": [
                {
                    "level_name": rl["level_name"],
                    "level_id": rl["level_id"],
                    "exit_type": rl["exit_type"],
                    "sort_order": rl["sort_order"],
                }
                for rl in run_levels
            ],
        })

    return {
        "game_name": game_name,
        "exported_at": utc_now_iso(),
        "levels": [
            {
                "level_name": lv["level_name"],
                "level_id": lv["level_id"],
                "has_secret_exit": bool(lv["has_secret_exit"]),
            }
            for lv in levels
        ],
        "runs": run_configs,
    }


def export_all_games() -> list[dict[str, Any]]:
    """Export configs for all games that have levels or runs defined."""
    game_names = set()
    for row in db.fetchall("SELECT DISTINCT game_name FROM game_levels"):
        game_names.add(row["game_name"])
    for row in db.fetchall("SELECT DISTINCT game_name FROM run_definitions"):
        game_names.add(row["game_name"])

    return [export_game_config(name) for name in sorted(game_names)]


def import_game_config(data: dict[str, Any], overwrite: bool = False) -> dict[str, Any]:
    """
    Import levels and runs for a game from exported JSON.

    If overwrite=True, deletes existing levels and runs for this game first.
    If overwrite=False, skips levels that already exist (matched by level_name).
    """
    game_name = data["game_name"]
    results = {"game_name": game_name, "levels_created": 0, "levels_skipped": 0,
               "runs_created": 0, "runs_skipped": 0}

    # Get existing levels for dedup
    existing_levels = get_levels_for_game(game_name)
    existing_level_names = {lv["level_name"] for lv in existing_levels}

    if overwrite:
        # Delete existing levels and runs
        db.execute("DELETE FROM run_levels WHERE run_definition_id IN (SELECT id FROM run_definitions WHERE game_name = ?)", (game_name,))
        db.execute("DELETE FROM run_definitions WHERE game_name = ?", (game_name,))
        db.execute("DELETE FROM game_levels WHERE game_name = ?", (game_name,))
        db.commit()
        existing_level_names = set()

    # Import levels
    level_name_to_id: dict[str, int] = {}

    for lv_data in data.get("levels", []):
        name = lv_data["level_name"]
        if name in existing_level_names:
            # Find existing level's DB id
            for elv in get_levels_for_game(game_name):
                if elv["level_name"] == name:
                    level_name_to_id[name] = elv["id"]
                    break
            results["levels_skipped"] += 1
            continue

        new_lv = create_level(
            game_name=game_name,
            level_name=name,
            level_id=lv_data.get("level_id"),
            has_secret_exit=lv_data.get("has_secret_exit", False),
        )
        level_name_to_id[name] = new_lv["id"]
        results["levels_created"] += 1

    # Refresh level list for run import
    all_levels = get_levels_for_game(game_name)
    for lv in all_levels:
        level_name_to_id[lv["level_name"]] = lv["id"]

    # Import runs
    existing_runs = get_runs_for_game(game_name)
    existing_run_names = {r["run_name"] for r in existing_runs}

    for run_data in data.get("runs", []):
        run_name = run_data["run_name"]
        if not overwrite and run_name in existing_run_names:
            results["runs_skipped"] += 1
            continue

        new_run = create_run(
            game_name=game_name,
            run_name=run_name,
            is_default=run_data.get("is_default", False),
            start_delay_ms=run_data.get("start_delay_ms", 0),
        )

        # Map run levels by level_name to game_level_id
        run_levels = []
        for rl_data in run_data.get("levels", []):
            gl_id = level_name_to_id.get(rl_data["level_name"])
            if gl_id:
                run_levels.append({
                    "game_level_id": gl_id,
                    "exit_type": rl_data.get("exit_type", "normal"),
                    "sort_order": rl_data.get("sort_order", 0),
                })

        if run_levels:
            set_run_levels(new_run["id"], run_levels)

        results["runs_created"] += 1

    return results
