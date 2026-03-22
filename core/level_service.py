"""Per-game level definitions — CRUD operations."""
from __future__ import annotations
from typing import Any
from core import db
from core.time_utils import utc_now_iso


def get_levels_for_game(game_name: str) -> list[dict[str, Any]]:
    return db.fetchall(
        "SELECT * FROM game_levels WHERE game_name = ? ORDER BY id", (game_name,)
    )


def get_level_by_id(level_id: int) -> dict[str, Any] | None:
    return db.fetchone("SELECT * FROM game_levels WHERE id = ?", (level_id,))


def create_level(game_name: str, level_name: str, level_id: str | None = None,
                 has_secret_exit: bool = False) -> dict[str, Any]:
    now = utc_now_iso()
    level_id_val = db.insert_returning_id(
        """INSERT INTO game_levels (game_name, level_name, level_id, has_secret_exit, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (game_name, level_name, level_id, int(has_secret_exit), now, now),
    )
    db.commit()
    return db.fetchone("SELECT * FROM game_levels WHERE id = ?", (level_id_val,)) or {}


def update_level(level_db_id: int, level_name: str | None = None, level_id: str | None = None,
                 has_secret_exit: bool | None = None) -> dict[str, Any] | None:
    existing = get_level_by_id(level_db_id)
    if not existing:
        return None
    now = utc_now_iso()
    new_name = level_name if level_name is not None else existing["level_name"]
    new_lid = level_id if level_id is not None else existing["level_id"]
    new_secret = int(has_secret_exit) if has_secret_exit is not None else existing["has_secret_exit"]
    db.execute(
        "UPDATE game_levels SET level_name=?, level_id=?, has_secret_exit=?, updated_at=? WHERE id=?",
        (new_name, new_lid, new_secret, now, level_db_id),
    )
    db.commit()
    return db.fetchone("SELECT * FROM game_levels WHERE id = ?", (level_db_id,))


def delete_level(level_db_id: int) -> bool:
    db.execute("DELETE FROM run_levels WHERE game_level_id = ?", (level_db_id,))
    db.execute("DELETE FROM game_levels WHERE id = ?", (level_db_id,))
    db.commit()
    return True


def set_level_id_from_hardware(level_db_id: int, hardware_level_id: str) -> dict[str, Any] | None:
    """Called when user presses capture button — sets the level_id from current hardware read."""
    return update_level(level_db_id, level_id=hardware_level_id)
