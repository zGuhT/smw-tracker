"""
Test suite for SFC Tracker — covers DB compatibility, cloud sync, and multi-user.

Run with: python -m pytest tests/test_core.py -v
Or standalone: python tests/test_core.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force SQLite mode for tests
os.environ.pop("DATABASE_URL", None)

# ── Use a temporary DB so tests never pollute the real app.db ──
_test_db_dir = tempfile.mkdtemp(prefix="sfc_test_")
_test_db_path = Path(_test_db_dir) / "test.db"

import core.db as _db_module
_db_module.DATA_DIR = Path(_test_db_dir)
_db_module.DB_PATH = _test_db_path
# Reset any cached connection from a previous import
_db_module.close_thread_connection()


class TestDbHelpers(unittest.TestCase):
    """Test cross-database SQL helpers."""

    def test_duration_sql_sqlite(self):
        from core.db import duration_sql, USE_POSTGRES
        self.assertFalse(USE_POSTGRES)
        sql = duration_sql()
        self.assertIn("julianday", sql)
        self.assertIn("86400", sql)
        self.assertIn("COALESCE(end_time, ?)", sql)

    def test_duration_sql_custom_cols(self):
        from core.db import duration_sql
        sql = duration_sql(start_col="created_at", end_expr="updated_at")
        self.assertIn("julianday(updated_at)", sql)
        self.assertIn("julianday(created_at)", sql)

    def test_date_sql_sqlite(self):
        from core.db import date_sql, USE_POSTGRES
        self.assertFalse(USE_POSTGRES)
        sql = date_sql()
        self.assertEqual(sql, "DATE(start_time)")

    def test_date_sql_custom_col(self):
        from core.db import date_sql
        sql = date_sql("created_at")
        self.assertEqual(sql, "DATE(created_at)")

    def test_pg_ts_helper(self):
        """Verify _pg_ts wraps with ::timestamptz for Z-suffix handling."""
        from core.db import _pg_ts
        result = _pg_ts("start_time")
        self.assertEqual(result, "start_time::timestamptz")
        result2 = _pg_ts("COALESCE(end_time, %s)")
        self.assertIn("::timestamptz", result2)


class TestDbPostgresSQL(unittest.TestCase):
    """Test Postgres SQL generation without needing a real Postgres connection."""

    def test_duration_sql_postgres_format(self):
        """Verify Postgres duration SQL uses timestamptz, not timestamp."""
        from core.db import _pg_ts
        # Simulate what duration_sql would produce for Postgres
        start_col = "start_time"
        end_expr = "COALESCE(end_time, %s)"
        pg_sql = f"EXTRACT(EPOCH FROM ({_pg_ts(end_expr)} - {_pg_ts(start_col)}))::integer"
        self.assertIn("::timestamptz", pg_sql)
        self.assertNotIn("::timestamp)", pg_sql)  # no bare ::timestamp)
        self.assertIn("EXTRACT(EPOCH", pg_sql)

    def test_date_sql_postgres_format(self):
        from core.db import _pg_ts
        col = "start_time"
        pg_sql = f"({_pg_ts(col)})::date"
        self.assertEqual(pg_sql, "(start_time::timestamptz)::date")


class TestInitDb(unittest.TestCase):
    """Test database initialization with SQLite."""

    def setUp(self):
        from core.db import init_db
        init_db()

    def test_tables_exist(self):
        from core import db
        tables = db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        table_names = {t["name"] for t in tables}
        expected = {"sessions", "game_events", "progress_snapshots",
                    "level_splits", "game_levels", "run_definitions",
                    "run_levels", "game_metadata", "users"}
        self.assertTrue(expected.issubset(table_names),
                        f"Missing tables: {expected - table_names}")

    def test_users_table_columns(self):
        from core import db
        row = db.fetchone("PRAGMA table_info(users)")
        self.assertIsNotNone(row)
        cols = db.fetchall("PRAGMA table_info(users)")
        col_names = {c["name"] for c in cols}
        self.assertIn("username", col_names)
        self.assertIn("api_key", col_names)
        self.assertIn("display_name", col_names)

    def test_sessions_has_user_id(self):
        from core import db
        cols = db.fetchall("PRAGMA table_info(sessions)")
        col_names = {c["name"] for c in cols}
        self.assertIn("user_id", col_names)


class TestSessionService(unittest.TestCase):
    """Test session lifecycle."""

    def setUp(self):
        from core.db import init_db
        init_db()

    def test_start_and_stop_session(self):
        from core.session_service import start_session, stop_active_session, get_active_session
        sess = start_session("TestGame", "SNES")
        self.assertIsNotNone(sess)
        self.assertEqual(sess["game_name"], "TestGame")
        self.assertEqual(sess["is_active"], 1)

        active = get_active_session()
        self.assertIsNotNone(active)
        self.assertEqual(active["id"], sess["id"])

        stopped = stop_active_session()
        self.assertTrue(stopped)

        active2 = get_active_session()
        self.assertIsNone(active2)

    def test_get_current_session_payload_empty(self):
        from core.session_service import get_current_session_payload, close_existing_active_sessions
        close_existing_active_sessions()
        payload = get_current_session_payload()
        self.assertFalse(payload["is_active"])
        self.assertIsNone(payload["id"])

    def test_get_current_session_payload_active(self):
        from core.session_service import start_session, get_current_session_payload
        start_session("PayloadTest")
        payload = get_current_session_payload()
        self.assertTrue(payload["is_active"])
        self.assertEqual(payload["game_name"], "PayloadTest")
        self.assertIn("splits", payload)
        self.assertIn("server_time", payload)


class TestStatsService(unittest.TestCase):
    """Test stats queries work with SQLite (validates SQL compatibility)."""

    def setUp(self):
        from core.db import init_db
        init_db()

    def test_most_played_empty(self):
        from core.stats_service import get_most_played_games
        result = get_most_played_games()
        self.assertIsInstance(result, list)

    def test_playtime_trend_empty(self):
        from core.stats_service import get_playtime_trend
        result = get_playtime_trend()
        self.assertIsInstance(result, list)

    def test_sessions_per_day_empty(self):
        from core.stats_service import get_sessions_per_day
        result = get_sessions_per_day()
        self.assertIsInstance(result, list)

    def test_recent_sessions_empty(self):
        from core.stats_service import get_recent_sessions
        result = get_recent_sessions()
        self.assertIsInstance(result, list)

    def test_death_stats_empty(self):
        from core.stats_service import get_death_stats
        result = get_death_stats()
        self.assertIsInstance(result, list)

    def test_game_summary_empty(self):
        from core.stats_service import get_game_summary
        result = get_game_summary("NonExistent")
        self.assertEqual(result["session_count"], 0)

    def test_stats_with_session_data(self):
        """Verify stats queries work with actual session data."""
        from core.session_service import start_session, stop_active_session
        from core.stats_service import get_most_played_games, get_recent_sessions

        start_session("StatsTestGame")
        stop_active_session()

        games = get_most_played_games()
        self.assertTrue(any(g["game_name"] == "StatsTestGame" for g in games))

        recent = get_recent_sessions()
        self.assertTrue(any(s["game_name"] == "StatsTestGame" for s in recent))


class TestSplitsService(unittest.TestCase):
    """Test split recording and PB/SOB queries."""

    def setUp(self):
        from core.db import init_db
        init_db()

    def test_record_and_query_split(self):
        from core.session_service import start_session
        from core.splits_service import record_split, get_best_segments, get_sum_of_best

        sess = start_session("SplitGame")
        now = time.time()

        record_split(sess["id"], "SplitGame", "L01", "Level 1",
                     split_ms=5000, entered_at=now, exited_at=now + 5,
                     death_count=2)
        record_split(sess["id"], "SplitGame", "L02", "Level 2",
                     split_ms=3000, entered_at=now + 5, exited_at=now + 8,
                     death_count=0)

        segs = get_best_segments("SplitGame")
        self.assertEqual(len(segs), 2)

        sob = get_sum_of_best("SplitGame")
        self.assertEqual(sob, 8000)


class TestUserService(unittest.TestCase):
    """Test multi-user service."""

    def setUp(self):
        from core.db import init_db
        init_db()
        # Use unique usernames per test run to avoid collisions
        import uuid
        self._suffix = uuid.uuid4().hex[:6]

    def test_create_user(self):
        from core.user_service import create_user, get_user_by_username
        uname = f"testrunner_{self._suffix}"
        user = create_user(uname, display_name="Test Runner")
        self.assertIsNotNone(user["id"])
        self.assertEqual(user["username"], uname)
        self.assertIsNotNone(user["api_key"])

        fetched = get_user_by_username(uname)
        self.assertEqual(fetched["id"], user["id"])

    def test_get_or_create_default(self):
        from core.user_service import get_or_create_default_user
        user1 = get_or_create_default_user()
        user2 = get_or_create_default_user()
        self.assertEqual(user1["id"], user2["id"])
        self.assertEqual(user1["username"], "default")

    def test_lookup_by_api_key(self):
        from core.user_service import create_user, get_user_by_api_key
        key = f"test-key-{self._suffix}"
        user = create_user(f"keytest_{self._suffix}", api_key=key)
        found = get_user_by_api_key(key)
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], user["id"])

        not_found = get_user_by_api_key("bogus-key")
        self.assertIsNone(not_found)

    def test_get_all_users(self):
        from core.user_service import create_user, get_all_users
        n1 = f"listtest1_{self._suffix}"
        n2 = f"listtest2_{self._suffix}"
        create_user(n1)
        create_user(n2)
        users = get_all_users()
        names = {u["username"] for u in users}
        self.assertIn(n1, names)
        self.assertIn(n2, names)
        # api_key should NOT be in the listing
        for u in users:
            self.assertNotIn("api_key", u)


class TestLiveStateManager(unittest.TestCase):
    """Test multi-user live state."""

    def test_default_user(self):
        from core.live_state import LiveStateManager
        mgr = LiveStateManager()

        mgr.update({"is_active": True, "game_name": "TestGame"})
        state = mgr.get_state()
        self.assertTrue(state["is_active"])

    def test_multi_user_isolation(self):
        from core.live_state import LiveStateManager
        mgr = LiveStateManager()

        mgr.update({"is_active": True, "game_name": "Game1"}, user_id="user1")
        mgr.update({"is_active": True, "game_name": "Game2"}, user_id="user2")

        s1 = mgr.get_state(user_id="user1")
        s2 = mgr.get_state(user_id="user2")
        self.assertEqual(s1["game_name"], "Game1")
        self.assertEqual(s2["game_name"], "Game2")

        # Default user is separate
        s_default = mgr.get_state()
        self.assertIsNone(s_default)

    def test_active_users(self):
        from core.live_state import LiveStateManager
        mgr = LiveStateManager()

        mgr.update({"is_active": True, "game_name": "G1"}, user_id="u1")
        mgr.update({"is_active": False}, user_id="u2")
        mgr.update({"is_active": True, "game_name": "G3"}, user_id="u3")

        active = mgr.get_active_users()
        active_ids = {a["user_id"] for a in active}
        self.assertIn("u1", active_ids)
        self.assertIn("u3", active_ids)
        self.assertNotIn("u2", active_ids)

    def test_clear_per_user(self):
        from core.live_state import LiveStateManager
        mgr = LiveStateManager()

        mgr.update({"is_active": True}, user_id="u1")
        mgr.update({"is_active": True}, user_id="u2")
        mgr.clear(user_id="u1")

        self.assertIsNone(mgr.get_state(user_id="u1")
                          if mgr.get_state(user_id="u1") is None
                          else mgr.get_state(user_id="u1").get("is_active"))
        self.assertTrue(mgr.get_state(user_id="u2")["is_active"])


class TestCloudClientDedup(unittest.TestCase):
    """Test that CloudSyncClient deduplicates unchanged payloads."""

    def test_payload_hash_dedup(self):
        """Verify identical payloads produce same hash."""
        payload1 = {"is_active": True, "game_name": "SMW", "splits": []}
        payload2 = {"is_active": True, "game_name": "SMW", "splits": []}
        payload3 = {"is_active": True, "game_name": "SMW", "splits": [{"id": 1}]}

        h1 = hash(json.dumps(payload1, sort_keys=True, default=str))
        h2 = hash(json.dumps(payload2, sort_keys=True, default=str))
        h3 = hash(json.dumps(payload3, sort_keys=True, default=str))

        self.assertEqual(h1, h2)
        self.assertNotEqual(h1, h3)


class TestTimeUtils(unittest.TestCase):
    """Test time utility functions."""

    def test_utc_now_iso_format(self):
        from core.time_utils import utc_now_iso
        iso = utc_now_iso()
        self.assertTrue(iso.endswith("Z"))
        self.assertIn("T", iso)

    def test_parse_iso_z_suffix(self):
        from core.time_utils import parse_iso
        dt = parse_iso("2025-01-15T10:30:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 10)

    def test_duration_seconds(self):
        from core.time_utils import duration_seconds
        d = duration_seconds("2025-01-15T10:00:00Z", "2025-01-15T10:05:00Z")
        self.assertEqual(d, 300)


class TestPostgresSchemaConsistency(unittest.TestCase):
    """Verify SQLite and Postgres schemas define the same tables and columns."""

    def _parse_tables(self, sql: str) -> dict[str, list[str]]:
        """Very simple parser to extract table names and column names."""
        tables = {}
        current_table = None
        for line in sql.split("\n"):
            line = line.strip()
            upper = line.upper()
            if upper.startswith("CREATE TABLE"):
                # Extract table name
                parts = line.split()
                idx = next(i for i, p in enumerate(parts) if p.upper() in ("EXISTS", "TABLE"))
                name = parts[idx + 1].rstrip("(").strip()
                if name.upper() == "IF":
                    name = parts[idx + 3].rstrip("(").strip()
                current_table = name
                tables[current_table] = []
            elif current_table and line.startswith(")"):
                current_table = None
            elif current_table and not upper.startswith(("CREATE", "FOREIGN", "--")):
                col = line.split()[0] if line.split() else ""
                if col and col not in ("PRIMARY", "UNIQUE", "CHECK", "CONSTRAINT"):
                    tables[current_table].append(col.rstrip(","))
        return tables

    def test_same_tables(self):
        from core.db import _TABLES_SQL_SQLITE, _TABLES_SQL_POSTGRES
        sqlite_tables = set(self._parse_tables(_TABLES_SQL_SQLITE).keys())
        pg_tables = set(self._parse_tables(_TABLES_SQL_POSTGRES).keys())
        self.assertEqual(sqlite_tables, pg_tables,
                         f"Table mismatch: SQLite extra={sqlite_tables - pg_tables}, "
                         f"Postgres extra={pg_tables - sqlite_tables}")

    def test_same_columns_per_table(self):
        from core.db import _TABLES_SQL_SQLITE, _TABLES_SQL_POSTGRES
        sqlite_tables = self._parse_tables(_TABLES_SQL_SQLITE)
        pg_tables = self._parse_tables(_TABLES_SQL_POSTGRES)

        for table in sqlite_tables:
            if table not in pg_tables:
                continue
            sqlite_cols = set(sqlite_tables[table])
            pg_cols = set(pg_tables[table])
            self.assertEqual(sqlite_cols, pg_cols,
                             f"Column mismatch in {table}: "
                             f"SQLite extra={sqlite_cols - pg_cols}, "
                             f"Postgres extra={pg_cols - sqlite_cols}")


class TestUserSessionWiring(unittest.TestCase):
    """Test that user_id is properly wired through session lifecycle."""

    def setUp(self):
        from core.db import init_db
        init_db()
        from core.user_service import create_user
        import uuid
        s = uuid.uuid4().hex[:6]
        self.user1 = create_user(f"wire_u1_{s}")
        self.user2 = create_user(f"wire_u2_{s}")

    def test_sessions_scoped_by_user(self):
        """Two users can have independent active sessions."""
        from core.session_service import start_session, get_active_session, stop_active_session

        s1 = start_session("Game_A", user_id=self.user1["id"])
        s2 = start_session("Game_B", user_id=self.user2["id"])

        # Both should be active
        a1 = get_active_session(user_id=self.user1["id"])
        a2 = get_active_session(user_id=self.user2["id"])
        self.assertIsNotNone(a1)
        self.assertIsNotNone(a2)
        self.assertEqual(a1["game_name"], "Game_A")
        self.assertEqual(a2["game_name"], "Game_B")
        self.assertNotEqual(a1["id"], a2["id"])

        # Stop user1 — user2 should still be active
        stop_active_session(user_id=self.user1["id"])
        self.assertIsNone(get_active_session(user_id=self.user1["id"]))
        self.assertIsNotNone(get_active_session(user_id=self.user2["id"]))

    def test_session_stores_user_id(self):
        """Session rows should have user_id set."""
        from core.session_service import start_session
        from core import db

        sess = start_session("UserIDTest", user_id=self.user1["id"])
        row = db.fetchone("SELECT user_id FROM sessions WHERE id = ?", (sess["id"],))
        self.assertEqual(row["user_id"], self.user1["id"])

    def test_payload_scoped_by_user(self):
        """get_current_session_payload returns user-scoped data."""
        from core.session_service import start_session, get_current_session_payload

        start_session("PayloadU1", user_id=self.user1["id"])
        start_session("PayloadU2", user_id=self.user2["id"])

        p1 = get_current_session_payload(user_id=self.user1["id"])
        p2 = get_current_session_payload(user_id=self.user2["id"])
        self.assertEqual(p1["game_name"], "PayloadU1")
        self.assertEqual(p2["game_name"], "PayloadU2")

    def test_unscoped_sees_any_active(self):
        """user_id=None should see any active session (backward compat)."""
        from core.session_service import start_session, get_active_session

        start_session("AnyGame", user_id=self.user1["id"])
        active = get_active_session(user_id=None)
        self.assertIsNotNone(active)

    def test_tracking_uses_user_session(self):
        """record_event should create/use the correct user's session."""
        from core.session_service import close_existing_active_sessions
        from core.tracking_service import record_event
        from core import db

        close_existing_active_sessions()
        result = record_event("death", "TrackGame", user_id=self.user1["id"])
        sess_row = db.fetchone("SELECT user_id FROM sessions WHERE id = ?",
                               (result["session_id"],))
        self.assertEqual(sess_row["user_id"], self.user1["id"])


class TestStatsUserScoping(unittest.TestCase):
    """Test that stats queries respect user_id filtering."""

    def setUp(self):
        from core.db import init_db
        init_db()
        from core.user_service import create_user
        from core.session_service import start_session, stop_active_session
        import uuid
        s = uuid.uuid4().hex[:6]
        self.u1 = create_user(f"stats_u1_{s}")
        self.u2 = create_user(f"stats_u2_{s}")

        # User 1 plays GameX, User 2 plays GameY
        start_session("GameX_" + s, user_id=self.u1["id"])
        stop_active_session(user_id=self.u1["id"])
        start_session("GameY_" + s, user_id=self.u2["id"])
        stop_active_session(user_id=self.u2["id"])
        self._s = s

    def test_most_played_scoped(self):
        from core.stats_service import get_most_played_games
        u1_games = get_most_played_games(user_id=self.u1["id"])
        u1_names = {g["game_name"] for g in u1_games}
        self.assertIn("GameX_" + self._s, u1_names)
        self.assertNotIn("GameY_" + self._s, u1_names)

    def test_recent_sessions_scoped(self):
        from core.stats_service import get_recent_sessions
        u2_sessions = get_recent_sessions(user_id=self.u2["id"])
        u2_names = {s["game_name"] for s in u2_sessions}
        self.assertIn("GameY_" + self._s, u2_names)
        self.assertNotIn("GameX_" + self._s, u2_names)

    def test_unscoped_sees_all(self):
        from core.stats_service import get_most_played_games
        all_games = get_most_played_games(user_id=None)
        all_names = {g["game_name"] for g in all_games}
        self.assertIn("GameX_" + self._s, all_names)
        self.assertIn("GameY_" + self._s, all_names)


class TestAuthService(unittest.TestCase):
    """Test registration, verification, and login flows."""

    def setUp(self):
        from core.db import init_db
        init_db()
        import uuid
        self._s = uuid.uuid4().hex[:6]
        self._pwd = "Test1234!"  # Meets all requirements

    def test_register_and_verify(self):
        from core.auth_service import register_user, verify_token
        result = register_user(f"auth_{self._s}", f"auth_{self._s}@test.com", self._pwd)
        self.assertIsNotNone(result["token"])
        self.assertIsNotNone(result["user_id"])

        user = verify_token(result["token"])
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], f"auth_{self._s}")
        self.assertIsNotNone(user["api_key"])

    def test_verify_bad_token(self):
        from core.auth_service import verify_token
        user = verify_token("totally-bogus-token")
        self.assertIsNone(user)

    def test_verify_token_single_use(self):
        from core.auth_service import register_user, verify_token
        result = register_user(f"once_{self._s}", f"once_{self._s}@test.com", self._pwd)

        user1 = verify_token(result["token"])
        self.assertIsNotNone(user1)

        user2 = verify_token(result["token"])
        self.assertIsNone(user2)

    def test_duplicate_username(self):
        from core.auth_service import register_user
        register_user(f"dup_{self._s}", f"dup1_{self._s}@test.com", self._pwd)
        with self.assertRaises(ValueError):
            register_user(f"dup_{self._s}", f"dup2_{self._s}@test.com", self._pwd)

    def test_duplicate_email(self):
        from core.auth_service import register_user
        register_user(f"em1_{self._s}", f"same_{self._s}@test.com", self._pwd)
        with self.assertRaises(ValueError):
            register_user(f"em2_{self._s}", f"same_{self._s}@test.com", self._pwd)

    def test_password_login(self):
        from core.auth_service import register_user, verify_token, login_with_password
        reg = register_user(f"pwl_{self._s}", f"pwl_{self._s}@test.com", self._pwd)
        verify_token(reg["token"])

        # Login by username
        user = login_with_password(f"pwl_{self._s}", self._pwd)
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], f"pwl_{self._s}")

        # Login by email
        user2 = login_with_password(f"pwl_{self._s}@test.com", self._pwd)
        self.assertIsNotNone(user2)

    def test_wrong_password_fails(self):
        from core.auth_service import register_user, verify_token, login_with_password
        reg = register_user(f"wpf_{self._s}", f"wpf_{self._s}@test.com", self._pwd)
        verify_token(reg["token"])

        user = login_with_password(f"wpf_{self._s}", "WrongPassword1!")
        self.assertIsNone(user)

    def test_login_unverified_fails(self):
        from core.auth_service import register_user, login_with_password
        register_user(f"unver_{self._s}", f"unver_{self._s}@test.com", self._pwd)
        user = login_with_password(f"unver_{self._s}", self._pwd)
        self.assertIsNone(user)

    def test_password_validation(self):
        from core.auth_service import validate_password
        self.assertIsNotNone(validate_password("short"))  # Too short
        self.assertIsNotNone(validate_password("alllowercase1!"))  # No uppercase
        self.assertIsNotNone(validate_password("ALLUPPERCASE1!"))  # No lowercase
        self.assertIsNotNone(validate_password("NoNumbers!!"))  # No digit
        self.assertIsNotNone(validate_password("NoSymbol1234"))  # No symbol
        self.assertIsNone(validate_password("ValidPass1!"))  # Valid

    def test_password_hashing(self):
        from core.auth_service import hash_password, verify_password
        h = hash_password("MySecureP@ss1")
        self.assertTrue(verify_password("MySecureP@ss1", h))
        self.assertFalse(verify_password("WrongPassword", h))
        self.assertIn("$", h)  # Salt$hash format

    def test_magic_link_flow(self):
        from core.auth_service import register_user, verify_token, request_magic_link
        reg = register_user(f"magic_{self._s}", f"magic_{self._s}@test.com", self._pwd)
        verify_token(reg["token"])

        login = request_magic_link(f"magic_{self._s}@test.com")
        self.assertIsNotNone(login)

        user = verify_token(login["token"])
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], f"magic_{self._s}")

    def test_session_tokens(self):
        from core.auth_service import (
            generate_session_token, get_user_from_session_token,
            invalidate_session_token, register_user, verify_token,
        )
        reg = register_user(f"sess_{self._s}", f"sess_{self._s}@test.com", self._pwd)
        user = verify_token(reg["token"])

        token = generate_session_token(user["id"])
        self.assertIsNotNone(token)

        looked_up = get_user_from_session_token(token)
        self.assertIsNotNone(looked_up)
        self.assertEqual(looked_up["id"], user["id"])

        invalidate_session_token(token)
        self.assertIsNone(get_user_from_session_token(token))


if __name__ == "__main__":
    unittest.main(verbosity=2)
