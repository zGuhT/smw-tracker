"""
Export local SQLite data to JSON for importing into the Railway PostgreSQL database.

Usage:
  python migrate_to_cloud.py export     # Creates data_export.json from local SQLite
  python migrate_to_cloud.py import     # Imports data_export.json into PostgreSQL (needs DATABASE_URL)
"""
import json
import os
import sys
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
EXPORT_FILE = BASE_DIR / "data_export.json"

TABLES = [
    "game_metadata",
    "game_levels",
    "run_definitions",
    "run_levels",
    "sessions",
    "game_events",
    "progress_snapshots",
    "level_splits",
]


def export_sqlite():
    if not DB_PATH.exists():
        print(f"No SQLite database found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    data = {}
    for table in TABLES:
        try:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            data[table] = [dict(r) for r in rows]
            print(f"  {table}: {len(data[table])} rows")
        except Exception as e:
            print(f"  {table}: SKIPPED ({e})")
            data[table] = []

    conn.close()

    with open(EXPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"\nExported to {EXPORT_FILE}")


def import_postgres():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Set DATABASE_URL environment variable first.")
        print("Get it from Railway dashboard → PostgreSQL → Connect → Connection String")
        sys.exit(1)

    if not EXPORT_FILE.exists():
        print(f"No export file found. Run 'python migrate_to_cloud.py export' first.")
        sys.exit(1)

    import psycopg2
    import psycopg2.extras

    with open(EXPORT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    conn = psycopg2.connect(database_url)
    cur = conn.cursor()

    # Init schema first
    sys.path.insert(0, str(BASE_DIR))
    os.environ["DATABASE_URL"] = database_url
    from core.db import init_db
    init_db()

    for table in TABLES:
        rows = data.get(table, [])
        if not rows:
            continue

        # Clear existing data
        cur.execute(f"DELETE FROM {table}")

        # Get column names from first row
        columns = list(rows[0].keys())
        placeholders = ", ".join(["%s"] * len(columns))
        col_names = ", ".join(columns)

        for row in rows:
            values = [row.get(c) for c in columns]
            try:
                cur.execute(f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", values)
            except Exception as e:
                print(f"  Error inserting into {table}: {e}")
                conn.rollback()
                cur = conn.cursor()
                continue

        # Reset the auto-increment sequence
        cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1)) FROM {table}")
        conn.commit()
        print(f"  {table}: {len(rows)} rows imported")

    cur.close()
    conn.close()
    print("\nImport complete!")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python migrate_to_cloud.py [export|import]")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == "export":
        print("Exporting SQLite data...")
        export_sqlite()
    elif cmd == "import":
        print("Importing to PostgreSQL...")
        import_postgres()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python migrate_to_cloud.py [export|import]")
