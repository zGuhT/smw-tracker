"""Shared time utilities used across services."""
from __future__ import annotations

from datetime import UTC, datetime


def utc_now_iso() -> str:
    """Return current UTC time as compact ISO-8601 string."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(dt_str: str | None) -> datetime | None:
    """Parse an ISO-8601 datetime string, handling the Z suffix."""
    if not dt_str:
        return None
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


def duration_seconds(start_time: str, end_time: str | None = None) -> int:
    """Calculate elapsed seconds between two ISO timestamps (or until now)."""
    start_dt = parse_iso(start_time)
    if start_dt is None:
        return 0
    end_dt = parse_iso(end_time) if end_time else datetime.now(UTC)
    if end_dt is None:
        end_dt = datetime.now(UTC)
    return max(0, int((end_dt - start_dt).total_seconds()))
