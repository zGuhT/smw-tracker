"""
User management — create, lookup, API key validation.

Multi-user model:
  - Each user gets a unique username and API key
  - Sessions are scoped to a user_id
  - The live state is keyed by user_id
  - A "default" user is auto-created for single-user/local setups
"""
from __future__ import annotations

import hashlib
import os
import secrets
from typing import Any

from core import db
from core.time_utils import utc_now_iso

DEFAULT_USERNAME = "default"


def generate_api_key() -> str:
    """Generate a secure random API key."""
    return secrets.token_urlsafe(32)


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    return db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))


def get_user_by_username(username: str) -> dict[str, Any] | None:
    return db.fetchone("SELECT * FROM users WHERE username = ?", (username,))


def get_user_by_api_key(api_key: str) -> dict[str, Any] | None:
    if not api_key:
        return None
    return db.fetchone("SELECT * FROM users WHERE api_key = ?", (api_key,))


def get_all_users(public_only: bool = True) -> list[dict[str, Any]]:
    if public_only:
        return db.fetchall(
            """SELECT id, username, display_name, created_at FROM users
               WHERE username != 'default' AND email_verified = 1
               ORDER BY id"""
        )
    return db.fetchall("SELECT id, username, display_name, created_at FROM users ORDER BY id")


def create_user(username: str, display_name: str | None = None,
                api_key: str | None = None) -> dict[str, Any]:
    now = utc_now_iso()
    if api_key is None:
        api_key = generate_api_key()
    user_id = db.insert_returning_id(
        """INSERT INTO users (username, display_name, api_key, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)""",
        (username, display_name or username, api_key, now, now),
    )
    db.commit()
    return db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,)) or {}


def get_or_create_default_user() -> dict[str, Any]:
    """Get or create the default user for single-user/local setups."""
    user = get_user_by_username(DEFAULT_USERNAME)
    if user:
        return user
    # Use SMW_API_KEY env var if set, otherwise generate one
    api_key = os.environ.get("SMW_API_KEY") or generate_api_key()
    return create_user(DEFAULT_USERNAME, display_name="Default", api_key=api_key)


def resolve_user_from_api_key(api_key: str) -> dict[str, Any] | None:
    """Look up user by API key. Used by cloud push to identify which user is pushing."""
    return get_user_by_api_key(api_key)
