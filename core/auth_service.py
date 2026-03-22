"""
Auth service — password-based authentication with email verification.

Registration flow:
  1. POST /auth/register {username, email, password, display_name, captcha_token}
     → Validates password strength, verifies captcha, creates user, sends verification email
  2. GET /auth/verify?token=xxx
     → Marks email verified, shows API key, sets session cookie

Login flow:
  1. POST /auth/login {username_or_email, password}
     → Validates credentials, sets session cookie
  2. Optionally: POST /auth/login {email} (no password)
     → Sends magic link email (fallback for forgotten passwords)
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from core import db
from core.time_utils import utc_now_iso
from core.user_service import generate_api_key, get_user_by_username


# ── Password hashing (PBKDF2-SHA256) ──

_HASH_ITERATIONS = 260_000  # OWASP recommendation for PBKDF2-SHA256


def hash_password(password: str) -> str:
    """Hash a password with a random salt. Returns 'salt$hash' string."""
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _HASH_ITERATIONS)
    return f"{salt}${h.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored 'salt$hash' string."""
    if not stored_hash or "$" not in stored_hash:
        return False
    salt, expected = stored_hash.split("$", 1)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _HASH_ITERATIONS)
    return secrets.compare_digest(h.hex(), expected)


# ── Password strength validation ──

def validate_password(password: str) -> str | None:
    """Validate password strength. Returns error message or None if valid.

    Requirements:
      - Minimum 8 characters
      - At least 1 uppercase letter
      - At least 1 lowercase letter
      - At least 1 digit
      - At least 1 special character
    """
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least 1 uppercase letter"
    if not re.search(r"[a-z]", password):
        return "Password must contain at least 1 lowercase letter"
    if not re.search(r"[0-9]", password):
        return "Password must contain at least 1 number"
    if not re.search(r"[^A-Za-z0-9]", password):
        return "Password must contain at least 1 special character"
    return None


# ── Captcha verification (Cloudflare Turnstile) ──

def verify_captcha(token: str) -> bool:
    """Verify a Cloudflare Turnstile captcha token. Returns True if valid.

    Requires TURNSTILE_SECRET_KEY env var. If not set, captcha is skipped (dev mode).
    """
    secret = os.environ.get("TURNSTILE_SECRET_KEY", "")
    if not secret:
        return True  # Skip captcha in dev mode

    try:
        resp = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret, "response": token},
            timeout=5,
        )
        result = resp.json()
        return result.get("success", False)
    except Exception:
        return False


# ── Token helpers ──

def _generate_token() -> str:
    """Generate a URL-safe verification token."""
    return secrets.token_urlsafe(48)


def _token_hash(token: str) -> str:
    """Hash a token for storage."""
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


# ── Registration ──

def register_user(username: str, email: str, password: str,
                  display_name: str | None = None) -> dict[str, Any]:
    """Create a new user with password. Returns raw verification token.

    Raises ValueError on validation failure.
    """
    username = username.strip().lower()
    email = email.strip().lower()

    if not username or not email or not password:
        raise ValueError("Username, email, and password are required")
    if len(username) < 2 or len(username) > 32:
        raise ValueError("Username must be 2-32 characters")
    if not re.match(r"^[a-z0-9_-]+$", username):
        raise ValueError("Username can only contain lowercase letters, numbers, underscores, and hyphens")
    if "@" not in email or "." not in email:
        raise ValueError("Invalid email address")

    # Validate password strength
    pwd_error = validate_password(password)
    if pwd_error:
        raise ValueError(pwd_error)

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
    token_hash_val = _token_hash(raw_token)
    api_key = generate_api_key()
    pwd_hash = hash_password(password)

    user_id = db.insert_returning_id(
        """INSERT INTO users (username, email, display_name, api_key, password_hash,
           email_verified, verification_token, verification_expires,
           created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
        (username, email, display_name or username, api_key, pwd_hash,
         token_hash_val, _expiry(24), now, now),
    )
    db.commit()

    return {
        "user_id": user_id,
        "username": username,
        "email": email,
        "token": raw_token,
    }


# ── Email verification ──

def verify_token(raw_token: str) -> dict[str, Any] | None:
    """Verify a token and activate the account. Returns user dict or None."""
    token_hash_val = _token_hash(raw_token)

    user = db.fetchone(
        "SELECT * FROM users WHERE verification_token = ?",
        (token_hash_val,),
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


# ── Password login ──

def login_with_password(username_or_email: str, password: str) -> dict[str, Any] | None:
    """Authenticate with username/email + password. Returns user dict or None."""
    identifier = username_or_email.strip().lower()

    # Try username first, then email
    user = db.fetchone("SELECT * FROM users WHERE username = ?", (identifier,))
    if not user:
        user = db.fetchone("SELECT * FROM users WHERE email = ?", (identifier,))
    if not user:
        return None

    # Check password
    if not user.get("password_hash"):
        return None  # Account has no password (legacy)
    if not verify_password(password, user["password_hash"]):
        return None

    # Must be email verified
    if not user.get("email_verified"):
        return None

    return {
        "id": user["id"],
        "username": user["username"],
        "email": user.get("email"),
        "display_name": user.get("display_name"),
        "api_key": user["api_key"],
    }


# ── Magic link login (fallback) ──

def request_magic_link(email: str) -> dict[str, Any] | None:
    """Generate a magic login link token for an existing verified user."""
    email = email.strip().lower()
    user = db.fetchone(
        "SELECT * FROM users WHERE email = ? AND email_verified = 1",
        (email,),
    )
    if not user:
        return None

    raw_token = _generate_token()
    token_hash_val = _token_hash(raw_token)
    now = utc_now_iso()

    db.execute(
        """UPDATE users SET verification_token = ?, verification_expires = ?,
           updated_at = ? WHERE id = ?""",
        (token_hash_val, _expiry(1), now, user["id"]),
    )
    db.commit()

    return {
        "user_id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "token": raw_token,
    }


# ── Resend verification ──

def resend_verification(email: str) -> dict[str, Any] | None:
    """Generate a fresh verification token for an unverified account."""
    email = email.strip().lower()
    user = db.fetchone(
        "SELECT * FROM users WHERE email = ? AND email_verified = 0",
        (email,),
    )
    if not user:
        return None

    raw_token = _generate_token()
    token_hash_val = _token_hash(raw_token)
    now = utc_now_iso()

    db.execute(
        """UPDATE users SET verification_token = ?, verification_expires = ?,
           updated_at = ? WHERE id = ?""",
        (token_hash_val, _expiry(24), now, user["id"]),
    )
    db.commit()

    return {
        "user_id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "token": raw_token,
    }


# ── Web session management ──

_web_sessions: dict[str, int] = {}


def generate_session_token(user_id: int) -> str:
    """Generate a web session token."""
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
    """Log out."""
    _web_sessions.pop(token, None)
