"""
In-memory live state manager.

Holds the current session state pushed by the local tracker.
Provides SSE broadcast to connected viewers.

Multi-user: state and subscribers are keyed by user_id.
The default user_id "default" is used for backward compatibility.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

DEFAULT_USER = "default"


class _UserState:
    """State container for a single user."""

    __slots__ = ("state", "updated_at", "subscribers", "pending_commands", "command_results")

    def __init__(self) -> None:
        self.state: dict[str, Any] | None = None
        self.updated_at: float = 0
        self.subscribers: list[asyncio.Queue] = []
        self.pending_commands: list[dict[str, Any]] = []
        self.command_results: dict[str, dict[str, Any]] = {}  # command_id → result


class LiveStateManager:
    """Thread-safe in-memory store for current session state, keyed per user."""

    def __init__(self) -> None:
        self._users: dict[str, _UserState] = {}

    def _get_user(self, user_id: str) -> _UserState:
        if user_id not in self._users:
            self._users[user_id] = _UserState()
        return self._users[user_id]

    # ── Backward-compatible single-user API ──

    _MENU_NAMES = {"m3nu", "menu", "m3nu.bin", "menu.bin"}

    @staticmethod
    def _is_menu_game(game_name: str | None) -> bool:
        if not game_name:
            return False
        lower = game_name.lower()
        return lower in LiveStateManager._MENU_NAMES or "menu" in lower or "m3nu" in lower

    def update(self, payload: dict[str, Any], user_id: str = DEFAULT_USER) -> None:
        """Update the current live state and notify all SSE subscribers."""
        # Filter out menu ROMs — don't store them as live state
        if self._is_menu_game(payload.get("game_name")):
            payload = dict(payload, is_active=False)

        us = self._get_user(user_id)
        us.state = payload
        us.updated_at = time.time()

        # Notify SSE subscribers
        dead = []
        for q in us.subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            us.subscribers.remove(q)

    def get_state(self, user_id: str = DEFAULT_USER) -> dict[str, Any] | None:
        us = self._users.get(user_id)
        return us.state if us else None

    def get_updated_at(self, user_id: str = DEFAULT_USER) -> float:
        us = self._users.get(user_id)
        return us.updated_at if us else 0

    def subscribe(self, user_id: str = DEFAULT_USER) -> asyncio.Queue:
        """Create a new SSE subscriber queue for a specific user's stream."""
        us = self._get_user(user_id)
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        us.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue, user_id: str = DEFAULT_USER) -> None:
        us = self._users.get(user_id)
        if us and q in us.subscribers:
            us.subscribers.remove(q)

    def clear(self, user_id: str = DEFAULT_USER) -> None:
        us = self._users.get(user_id)
        if us:
            us.state = None
            us.updated_at = 0

    # ── Multi-user queries ──

    def get_active_users(self) -> list[dict[str, Any]]:
        """Return a list of user_ids that have active sessions."""
        result = []
        now = time.time()
        for uid, us in self._users.items():
            if us.state and us.state.get("is_active"):
                if self._is_menu_game(us.state.get("game_name")):
                    continue
                result.append({
                    "user_id": uid,
                    "game_name": us.state.get("game_name"),
                    "age_seconds": round(now - us.updated_at, 1),
                })
        return result

    # ── Command queue (web → local tracker) ──

    def queue_command(self, user_id: str, command: dict[str, Any]) -> str:
        """Queue a command for the user's local tracker. Returns command_id."""
        import secrets
        cmd_id = secrets.token_hex(8)
        command["command_id"] = cmd_id
        us = self._get_user(user_id)
        us.pending_commands.append(command)
        return cmd_id

    def drain_commands(self, user_id: str) -> list[dict[str, Any]]:
        """Get and clear all pending commands for a user (called on push response)."""
        us = self._users.get(user_id)
        if not us or not us.pending_commands:
            return []
        cmds = us.pending_commands[:]
        us.pending_commands.clear()
        return cmds

    def store_command_result(self, user_id: str, command_id: str, result: dict[str, Any]) -> None:
        """Store a command result from the local tracker."""
        us = self._get_user(user_id)
        us.command_results[command_id] = result

    def get_command_result(self, user_id: str, command_id: str) -> dict[str, Any] | None:
        """Get a command result (and remove it)."""
        us = self._users.get(user_id)
        if not us:
            return None
        return us.command_results.pop(command_id, None)

    @property
    def _subscribers(self) -> list[asyncio.Queue]:
        """Backward compat: return default user's subscriber list."""
        return self._get_user(DEFAULT_USER).subscribers


# Global singleton
live_state = LiveStateManager()
