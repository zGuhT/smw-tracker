"""
Database layer supporting both SQLite (local) and PostgreSQL (cloud).

Set DATABASE_URL environment variable to use PostgreSQL:
  DATABASE_URL=postgresql://user:pass@host:5432/dbname

Without DATABASE_URL, falls back to local SQLite at data/app.db.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_POSTGRES = DATABASE_URL.startswith("postgres")

_local = threading.local()

# ── Connection management ──

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

    def get_connection():
        conn = getattr(_local, "conn", None)
        if conn is not None:
            try:
                conn.execute("SELECT 1") if hasattr(conn, 'execute') else None
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                return conn
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        _local.conn = conn
        return conn

    def close_thread_connection() -> None:
        conn = getattr(_local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            _local.conn = None

    def execute(sql: str, params: tuple[Any, ...] = ()):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(_pg_sql(sql), params)
        return cur

    def executemany(sql: str, seq: list[tuple[Any, ...]]):
        conn = get_connection()
        cur = conn.cursor()
        for params in seq:
            cur.execute(_pg_sql(sql), params)
        return cur

    def fetchone(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(_pg_sql(sql), params)
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None

    def fetchall(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(_pg_sql(sql), params)
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]

    def commit() -> None:
        get_connection().commit()

    def _pg_sql(sql: str) -> str:
        """Convert SQLite ? placeholders to PostgreSQL %s."""
        return sql.replace("?", "%s")

else:
    import sqlite3

    def get_connection() -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(_local, "conn", None)
        if conn is not None:
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.ProgrammingError:
                pass
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        _local.conn = conn
        return conn

    def close_thread_connection() -> None:
        conn: sqlite3.Connection | None = getattr(_local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            _local.conn = None

    def execute(sql: str, params: tuple[Any, ...] = ()):
        return get_connection().execute(sql, params)

    def executemany(sql: str, seq: list[tuple[Any, ...]]):
        return get_connection().executemany(sql, seq)

    def fetchone(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        row = get_connection().execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetchall(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        rows = get_connection().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def commit() -> None:
        get_connection().commit()


# ── Schema init ──

_TABLES_SQL_SQLITE = """
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_name TEXT NOT NULL, platform TEXT,
        start_time TEXT NOT NULL, end_time TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        last_event_time TEXT,
        run_definition_id INTEGER,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS game_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL, game_name TEXT NOT NULL,
        event_type TEXT NOT NULL, event_time TEXT NOT NULL,
        level_id TEXT, level_name TEXT, x_position INTEGER,
        details_json TEXT, created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS progress_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL, game_name TEXT NOT NULL,
        snapshot_time TEXT NOT NULL,
        level_id TEXT, level_name TEXT, x_position INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS level_splits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL, game_name TEXT NOT NULL,
        level_id TEXT NOT NULL, level_name TEXT,
        split_ms INTEGER NOT NULL,
        entered_at REAL NOT NULL, exited_at REAL NOT NULL,
        death_count INTEGER NOT NULL DEFAULT 0,
        best_x INTEGER, created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS game_levels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_name TEXT NOT NULL, level_name TEXT NOT NULL,
        level_id TEXT, has_secret_exit INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS run_definitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_name TEXT NOT NULL, run_name TEXT NOT NULL,
        is_default INTEGER NOT NULL DEFAULT 0,
        start_delay_ms INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS run_levels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_definition_id INTEGER NOT NULL,
        game_level_id INTEGER NOT NULL,
        exit_type TEXT NOT NULL DEFAULT 'normal',
        sort_order INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (run_definition_id) REFERENCES run_definitions(id) ON DELETE CASCADE,
        FOREIGN KEY (game_level_id) REFERENCES game_levels(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS game_metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rom_path TEXT, rom_name TEXT NOT NULL,
        normalized_name TEXT NOT NULL, platform_name TEXT,
        source TEXT, external_game_id TEXT,
        display_name TEXT, overview TEXT, genres_json TEXT,
        release_date TEXT, developer TEXT, publisher TEXT,
        players TEXT, rating TEXT,
        boxart_url TEXT, screenshot_url TEXT,
        fanart_url TEXT, banner_url TEXT,
        raw_json TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(is_active);
    CREATE INDEX IF NOT EXISTS idx_sessions_game_name ON sessions(game_name);
    CREATE INDEX IF NOT EXISTS idx_game_events_session ON game_events(session_id);
    CREATE INDEX IF NOT EXISTS idx_game_events_type ON game_events(event_type);
    CREATE INDEX IF NOT EXISTS idx_game_events_session_type ON game_events(session_id, event_type);
    CREATE INDEX IF NOT EXISTS idx_progress_snapshots_session ON progress_snapshots(session_id);
    CREATE INDEX IF NOT EXISTS idx_level_splits_game ON level_splits(game_name);
    CREATE INDEX IF NOT EXISTS idx_level_splits_session ON level_splits(session_id);
    CREATE INDEX IF NOT EXISTS idx_level_splits_game_level ON level_splits(game_name, level_id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_game_metadata_rom_name ON game_metadata(rom_name);
    CREATE INDEX IF NOT EXISTS idx_game_levels_game ON game_levels(game_name);
    CREATE INDEX IF NOT EXISTS idx_run_definitions_game ON run_definitions(game_name);
    CREATE INDEX IF NOT EXISTS idx_run_levels_run ON run_levels(run_definition_id);
"""

_TABLES_SQL_POSTGRES = """
    CREATE TABLE IF NOT EXISTS sessions (
        id SERIAL PRIMARY KEY,
        game_name TEXT NOT NULL, platform TEXT,
        start_time TEXT NOT NULL, end_time TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        last_event_time TEXT,
        run_definition_id INTEGER,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS game_events (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        game_name TEXT NOT NULL,
        event_type TEXT NOT NULL, event_time TEXT NOT NULL,
        level_id TEXT, level_name TEXT, x_position INTEGER,
        details_json TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS progress_snapshots (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        game_name TEXT NOT NULL,
        snapshot_time TEXT NOT NULL,
        level_id TEXT, level_name TEXT, x_position INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS level_splits (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        game_name TEXT NOT NULL,
        level_id TEXT NOT NULL, level_name TEXT,
        split_ms INTEGER NOT NULL,
        entered_at DOUBLE PRECISION NOT NULL, exited_at DOUBLE PRECISION NOT NULL,
        death_count INTEGER NOT NULL DEFAULT 0,
        best_x INTEGER, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS game_levels (
        id SERIAL PRIMARY KEY,
        game_name TEXT NOT NULL, level_name TEXT NOT NULL,
        level_id TEXT, has_secret_exit INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS run_definitions (
        id SERIAL PRIMARY KEY,
        game_name TEXT NOT NULL, run_name TEXT NOT NULL,
        is_default INTEGER NOT NULL DEFAULT 0,
        start_delay_ms INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS run_levels (
        id SERIAL PRIMARY KEY,
        run_definition_id INTEGER NOT NULL REFERENCES run_definitions(id) ON DELETE CASCADE,
        game_level_id INTEGER NOT NULL REFERENCES game_levels(id) ON DELETE CASCADE,
        exit_type TEXT NOT NULL DEFAULT 'normal',
        sort_order INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS game_metadata (
        id SERIAL PRIMARY KEY,
        rom_path TEXT, rom_name TEXT NOT NULL,
        normalized_name TEXT NOT NULL, platform_name TEXT,
        source TEXT, external_game_id TEXT,
        display_name TEXT, overview TEXT, genres_json TEXT,
        release_date TEXT, developer TEXT, publisher TEXT,
        players TEXT, rating TEXT,
        boxart_url TEXT, screenshot_url TEXT,
        fanart_url TEXT, banner_url TEXT,
        raw_json TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(is_active);
    CREATE INDEX IF NOT EXISTS idx_sessions_game_name ON sessions(game_name);
    CREATE INDEX IF NOT EXISTS idx_game_events_session ON game_events(session_id);
    CREATE INDEX IF NOT EXISTS idx_game_events_type ON game_events(event_type);
    CREATE INDEX IF NOT EXISTS idx_game_events_session_type ON game_events(session_id, event_type);
    CREATE INDEX IF NOT EXISTS idx_progress_snapshots_session ON progress_snapshots(session_id);
    CREATE INDEX IF NOT EXISTS idx_level_splits_game ON level_splits(game_name);
    CREATE INDEX IF NOT EXISTS idx_level_splits_session ON level_splits(session_id);
    CREATE INDEX IF NOT EXISTS idx_level_splits_game_level ON level_splits(game_name, level_id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_game_metadata_rom_name ON game_metadata(rom_name);
    CREATE INDEX IF NOT EXISTS idx_game_levels_game ON game_levels(game_name);
    CREATE INDEX IF NOT EXISTS idx_run_definitions_game ON run_definitions(game_name);
    CREATE INDEX IF NOT EXISTS idx_run_levels_run ON run_levels(run_definition_id);
"""


def insert_returning_id(sql: str, params: tuple[Any, ...] = ()) -> int | None:
    """Execute an INSERT and return the new row's id.
    Works with both SQLite (lastrowid) and PostgreSQL (RETURNING id).
    """
    if USE_POSTGRES:
        # Append RETURNING id if not already present
        if "RETURNING" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(_pg_sql(sql), params)
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    else:
        cur = get_connection().execute(sql, params)
        return cur.lastrowid


def init_db() -> None:
    if USE_POSTGRES:
        conn = get_connection()
        cur = conn.cursor()
        # Execute each statement separately for PostgreSQL
        for stmt in _TABLES_SQL_POSTGRES.split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    cur.execute(stmt)
                except Exception:
                    conn.rollback()
                    cur = conn.cursor()
                    continue
        conn.commit()
        cur.close()
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = get_connection()
        conn.executescript(_TABLES_SQL_SQLITE)
        # Safe column migrations for older SQLite DBs
        for migration in [
            "ALTER TABLE sessions ADD COLUMN run_definition_id INTEGER",
            "ALTER TABLE game_metadata ADD COLUMN developer TEXT",
            "ALTER TABLE game_metadata ADD COLUMN publisher TEXT",
            "ALTER TABLE game_metadata ADD COLUMN players TEXT",
            "ALTER TABLE game_metadata ADD COLUMN rating TEXT",
            "ALTER TABLE game_metadata ADD COLUMN fanart_url TEXT",
            "ALTER TABLE game_metadata ADD COLUMN banner_url TEXT",
        ]:
            try:
                conn.execute(migration)
            except Exception:
                pass
        conn.commit()
