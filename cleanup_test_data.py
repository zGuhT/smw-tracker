"""
Remove test data that was accidentally written to the real app.db.

Usage: python cleanup_test_data.py
       python cleanup_test_data.py --dry-run   (preview what would be deleted)

This removes sessions (and their cascaded events/splits/snapshots) for games
that were created by the test suite, plus any test users.
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "app.db"

# Games created by the test suite — these don't come from real SNES hardware
TEST_GAME_NAMES = [
    "TestGame", "PayloadTest", "PayloadU1", "PayloadU2",
    "StatsTestGame", "SplitGame", "Game_A", "Game_B",
    "UserIDTest", "AnyGame", "TrackGame", "NonExistent",
]


def main():
    dry_run = "--dry-run" in sys.argv

    if not DB_PATH.exists():
        print(f"No database at {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Find test sessions
    placeholders = ",".join("?" for _ in TEST_GAME_NAMES)
    sessions = conn.execute(
        f"SELECT id, game_name, start_time FROM sessions WHERE game_name IN ({placeholders})",
        TEST_GAME_NAMES,
    ).fetchall()

    if not sessions:
        print("No test data found — your DB is clean.")
        conn.close()
        return

    print(f"Found {len(sessions)} test session(s) to remove:")
    for s in sessions:
        print(f"  id={s['id']}  game={s['game_name']}  started={s['start_time']}")

    # Count related records
    session_ids = [s["id"] for s in sessions]
    id_placeholders = ",".join("?" for _ in session_ids)

    events = conn.execute(
        f"SELECT COUNT(*) AS c FROM game_events WHERE session_id IN ({id_placeholders})",
        session_ids,
    ).fetchone()["c"]
    snapshots = conn.execute(
        f"SELECT COUNT(*) AS c FROM progress_snapshots WHERE session_id IN ({id_placeholders})",
        session_ids,
    ).fetchone()["c"]
    splits = conn.execute(
        f"SELECT COUNT(*) AS c FROM level_splits WHERE session_id IN ({id_placeholders})",
        session_ids,
    ).fetchone()["c"]

    print(f"\nRelated records: {events} events, {snapshots} snapshots, {splits} splits")

    # Find test users (not the default user, and not created before the test run)
    test_users = conn.execute(
        "SELECT id, username FROM users WHERE username != 'default' AND username LIKE '%\\_%' ESCAPE '\\'",
    ).fetchall()

    if test_users:
        print(f"\nFound {len(test_users)} test user(s):")
        for u in test_users:
            print(f"  id={u['id']}  username={u['username']}")

    if dry_run:
        print("\n[DRY RUN] No changes made. Run without --dry-run to delete.")
        conn.close()
        return

    confirm = input("\nDelete all test data? [y/N] ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        conn.close()
        return

    # Delete sessions (cascades to events, snapshots, splits)
    conn.execute(
        f"DELETE FROM game_events WHERE session_id IN ({id_placeholders})", session_ids
    )
    conn.execute(
        f"DELETE FROM progress_snapshots WHERE session_id IN ({id_placeholders})", session_ids
    )
    conn.execute(
        f"DELETE FROM level_splits WHERE session_id IN ({id_placeholders})", session_ids
    )
    conn.execute(
        f"DELETE FROM sessions WHERE id IN ({id_placeholders})", session_ids
    )

    # Delete test users
    if test_users:
        user_ids = [u["id"] for u in test_users]
        uid_ph = ",".join("?" for _ in user_ids)
        conn.execute(f"DELETE FROM users WHERE id IN ({uid_ph})", user_ids)

    conn.commit()
    conn.close()
    print("Done — test data removed.")


if __name__ == "__main__":
    main()
