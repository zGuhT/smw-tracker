"""
In-memory live state manager.

Holds the current session state pushed by the local tracker.
Provides SSE broadcast to connected viewers.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any


class LiveStateManager:
    """Thread-safe in-memory store for current session state."""

    def __init__(self) -> None:
        self._state: dict[str, Any] | None = None
        self._updated_at: float = 0
        self._subscribers: list[asyncio.Queue] = []

    def update(self, payload: dict[str, Any]) -> None:
        """Update the current live state and notify all SSE subscribers."""
        self._state = payload
        self._updated_at = time.time()

        # Notify SSE subscribers
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    def get_state(self) -> dict[str, Any] | None:
        return self._state

    def get_updated_at(self) -> float:
        return self._updated_at

    def subscribe(self) -> asyncio.Queue:
        """Create a new SSE subscriber queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def clear(self) -> None:
        self._state = None
        self._updated_at = 0


# Global singleton
live_state = LiveStateManager()
