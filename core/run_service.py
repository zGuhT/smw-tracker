"""Run definitions — named run configs with ordered level lists."""
from __future__ import annotations
from typing import Any
from core import db
from core.time_utils import utc_now_iso


def get_runs_for_game(game_name: str) -> list[dict[str, Any]]:
    return db.fetchall(
        "SELECT * FROM run_definitions WHERE game_name = ? ORDER BY is_default DESC, run_name",
        (game_name,),
    )


def get_run_by_id(run_id: int) -> dict[str, Any] | None:
    return db.fetchone("SELECT * FROM run_definitions WHERE id = ?", (run_id,))


def get_default_run_for_game(game_name: str) -> dict[str, Any] | None:
    return db.fetchone(
        "SELECT * FROM run_definitions WHERE game_name = ? AND is_default = 1 ORDER BY id DESC LIMIT 1",
        (game_name,),
    )


def create_run(game_name: str, run_name: str, is_default: bool = False,
               start_delay_ms: int = 0) -> dict[str, Any]:
    now = utc_now_iso()
    if is_default:
        db.execute("UPDATE run_definitions SET is_default = 0 WHERE game_name = ?", (game_name,))
    run_id_val = db.insert_returning_id(
        """INSERT INTO run_definitions (game_name, run_name, is_default, start_delay_ms, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (game_name, run_name, int(is_default), start_delay_ms, now, now),
    )
    db.commit()
    return db.fetchone("SELECT * FROM run_definitions WHERE id = ?", (run_id_val,)) or {}


def update_run(run_id: int, run_name: str | None = None, is_default: bool | None = None,
               start_delay_ms: int | None = None) -> dict[str, Any] | None:
    existing = get_run_by_id(run_id)
    if not existing:
        return None
    now = utc_now_iso()
    game_name = existing["game_name"]
    new_name = run_name if run_name is not None else existing["run_name"]
    new_delay = start_delay_ms if start_delay_ms is not None else existing["start_delay_ms"]
    new_default = int(is_default) if is_default is not None else existing["is_default"]
    if new_default and not existing["is_default"]:
        db.execute("UPDATE run_definitions SET is_default = 0 WHERE game_name = ?", (game_name,))
    db.execute(
        "UPDATE run_definitions SET run_name=?, is_default=?, start_delay_ms=?, updated_at=? WHERE id=?",
        (new_name, new_default, new_delay, now, run_id),
    )
    db.commit()
    return db.fetchone("SELECT * FROM run_definitions WHERE id = ?", (run_id,))


def delete_run(run_id: int) -> bool:
    db.execute("DELETE FROM run_levels WHERE run_definition_id = ?", (run_id,))
    db.execute("DELETE FROM run_definitions WHERE id = ?", (run_id,))
    db.commit()
    return True


def get_run_levels(run_id: int) -> list[dict[str, Any]]:
    """Get the ordered level list for a run, joined with game_levels for names."""
    return db.fetchall(
        """SELECT rl.id, rl.run_definition_id, rl.game_level_id, rl.exit_type, rl.sort_order,
                  gl.level_name, gl.level_id, gl.has_secret_exit, gl.game_name
           FROM run_levels rl
           JOIN game_levels gl ON gl.id = rl.game_level_id
           WHERE rl.run_definition_id = ?
           ORDER BY rl.sort_order""",
        (run_id,),
    )


def set_run_levels(run_id: int, levels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace the entire ordered level list for a run.
    Each entry: {game_level_id: int, exit_type: 'normal'|'secret', sort_order: int}
    """
    db.execute("DELETE FROM run_levels WHERE run_definition_id = ?", (run_id,))
    for entry in levels:
        db.execute(
            """INSERT INTO run_levels (run_definition_id, game_level_id, exit_type, sort_order)
            VALUES (?, ?, ?, ?)""",
            (run_id, entry["game_level_id"], entry.get("exit_type", "normal"), entry.get("sort_order", 0)),
        )
    db.commit()
    return get_run_levels(run_id)


def get_full_run_config(run_id: int) -> dict[str, Any] | None:
    """Get a run definition with its ordered levels — everything the tracker needs."""
    run = get_run_by_id(run_id)
    if not run:
        return None
    levels = get_run_levels(run_id)
    return {**run, "levels": levels}


def get_default_run_config(game_name: str) -> dict[str, Any] | None:
    """Get the default run for a game with full level list."""
    run = get_default_run_for_game(game_name)
    if not run:
        return None
    return get_full_run_config(run["id"])
