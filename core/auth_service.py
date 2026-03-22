"""
Auth service — passwordless email-based authentication.

Flow:
  1. Register: POST /auth/register {username, email}
     → Creates unverified user, sends verification email
  2. Verify: GET /auth/verify?token=xxx
     → Marks email verified, shows API key, sets session cookie
  3. Login: POST /auth/login {email}
     → Sends magic link email with short-lived token
  4. Magic link: GET /auth/verify?token=xxx (same endpoint)
     → Sets session cookie, redirects to profile
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from core import db
from core.time_utils import utc_now_iso
from core.user_service import generate_api_key, get_user_by_username


def _generate_token() -> str:
    """Generate a URL-safe verification token."""
    return secrets.token_urlsafe(48)


def _token_hash(token: str) -> str:
    """Hash a token for storage. We store hashes, not raw tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


def _expiry(hours: int = 24) -> str:
    """Return an ISO timestamp `hours` from now."""
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def _is_expired(expiry_str: str | None) -> bool:
    """Check if a token has expired."""
    if not expiry_str:
        return True
    try:
        expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        return datetime.now(UTC) > expiry
    except (ValueError, TypeError):
        return True


def register_user(username: str, email: str, display_name: str | None = None) -> dict[str, Any]:
    """Create a new unverified user and return the raw verification token.

    Raises ValueError if username or email is already taken.
    """
    username = username.strip().lower()
    email = email.strip().lower()

    if not username or not email:
        raise ValueError("Username and email are required")
    if len(username) < 2 or len(username) > 32:
        raise ValueError("Username must be 2-32 characters")
    if "@" not in email or "." not in email:
        raise ValueError("Invalid email address")

    # Check for existing username
    existing = db.fetchone("SELECT id FROM users WHERE username = ?", (username,))
    if existing:
        raise ValueError(f"Username '{username}' is already taken")

    # Check for existing email
    existing_email = db.fetchone("SELECT id FROM users WHERE email = ?", (email,))
    if existing_email:
        raise ValueError("An account with this email already exists")

    now = utc_now_iso()
    raw_token = _generate_token()
    token_hash = _token_hash(raw_token)
    api_key = generate_api_key()

    user_id = db.insert_returning_id(
        """INSERT INTO users (username, email, display_name, api_key,
           email_verified, verification_token, verification_expires,
           created_at, updated_at)
        VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)""",
        (username, email, display_name or username, api_key,
         token_hash, _expiry(24), now, now),
    )
    db.commit()

    return {
        "user_id": user_id,
        "username": username,
        "email": email,
        "token": raw_token,  # Raw token — only returned here, sent via email
    }


def verify_token(raw_token: str) -> dict[str, Any] | None:
    """Verify a token and activate the account. Returns user dict or None."""
    token_hash = _token_hash(raw_token)

    user = db.fetchone(
        "SELECT * FROM users WHERE verification_token = ?",
        (token_hash,),
    )
    if not user:
        return None

    if _is_expired(user.get("verification_expires")):
        return None

    now = utc_now_iso()
    db.execute(
        """UPDATE users SET email_verified = 1,
           verification_token = NULL, verification_expires = NULL,
           updated_at = ? WHERE id = ?""",
        (now, user["id"]),
    )
    db.commit()

    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "display_name": user.get("display_name"),
        "api_key": user["api_key"],
    }


def request_login(email: str) -> dict[str, Any] | None:
    """Generate a magic login link token for an existing verified user.

    Returns {user_id, username, token} or None if user not found.
    """
    email = email.strip().lower()
    user = db.fetchone(
        "SELECT * FROM users WHERE email = ? AND email_verified = 1",
        (email,),
    )
    if not user:
        return None

    raw_token = _generate_token()
    token_hash = _token_hash(raw_token)
    now = utc_now_iso()

    db.execute(
        """UPDATE users SET verification_token = ?, verification_expires = ?,
           updated_at = ? WHERE id = ?""",
        (token_hash, _expiry(1), now, user["id"]),
    )
    db.commit()

    return {
        "user_id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "token": raw_token,
    }


def resend_verification(email: str) -> dict[str, Any] | None:
    """Generate a fresh verification token for an unverified account.

    Returns {user_id, username, email, token} or None if not found / already verified.
    """
    email = email.strip().lower()
    user = db.fetchone(
        "SELECT * FROM users WHERE email = ? AND email_verified = 0",
        (email,),
    )
    if not user:
        return None

    raw_token = _generate_token()
    token_hash = _token_hash(raw_token)
    now = utc_now_iso()

    db.execute(
        """UPDATE users SET verification_token = ?, verification_expires = ?,
           updated_at = ? WHERE id = ?""",
        (token_hash, _expiry(24), now, user["id"]),
    )
    db.commit()

    return {
        "user_id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "token": raw_token,
    }


def generate_session_token(user_id: int) -> str:
    """Generate a web session token (stored as a signed cookie value).

    We use a simple approach: a random token stored in a lookup table (in-memory).
    For a small-scale app this is fine. For production scale, use JWT or Redis.
    """
    token = secrets.token_urlsafe(32)
    _web_sessions[token] = user_id
    return token


def get_user_from_session_token(token: str | None) -> dict[str, Any] | None:
    """Look up a user from a web session token."""
    if not token:
        return None
    user_id = _web_sessions.get(token)
    if user_id is None:
        return None
    from core.user_service import get_user_by_id
    return get_user_by_id(user_id)


def invalidate_session_token(token: str) -> None:
    """Log out — remove a web session."""
    _web_sessions.pop(token, None)


# In-memory web session store (cleared on restart, which is fine for this scale)
_web_sessions: dict[str, int] = {}
