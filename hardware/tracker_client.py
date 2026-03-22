"""
Tracker client abstraction — Direct (in-process) and HTTP variants.

All clients accept an optional user_id to scope sessions to a specific user.
"""
from __future__ import annotations

import abc
from typing import Any

import requests


class TrackerClient(abc.ABC):
    """Abstract tracker client. Implementations may set self.user_id."""

    def __init__(self, user_id: int | None = None) -> None:
        self.user_id = user_id

    @abc.abstractmethod
    def get_current_session(self) -> dict[str, Any]: ...
    @abc.abstractmethod
    def stop_session(self) -> dict[str, Any]: ...
    @abc.abstractmethod
    def post_progress(self, game_name: str, level_id: str | None,
                      level_name: str | None, x_position: int | None) -> dict[str, Any]: ...
    @abc.abstractmethod
    def post_event(self, event_type: str, game_name: str, level_id: str | None,
                   level_name: str | None, x_position: int | None,
                   details: dict[str, Any] | None = None) -> dict[str, Any]: ...
    @abc.abstractmethod
    def record_split(self, session_id: int, game_name: str, level_id: str,
                     level_name: str | None, split_ms: int, entered_at: float,
                     exited_at: float, death_count: int = 0,
                     best_x: int | None = None) -> dict[str, Any]: ...


class DirectServiceClient(TrackerClient):
    def get_current_session(self) -> dict[str, Any]:
        from core.session_service import get_current_session_payload
        return get_current_session_payload(user_id=self.user_id)

    def stop_session(self) -> dict[str, Any]:
        from core.session_service import stop_active_session
        return {"success": stop_active_session(user_id=self.user_id)}

    def post_progress(self, game_name: str, level_id: str | None,
                      level_name: str | None, x_position: int | None) -> dict[str, Any]:
        from core.tracking_service import record_progress
        return record_progress(game_name=game_name, level_id=level_id,
                               level_name=level_name, x_position=x_position,
                               user_id=self.user_id)

    def post_event(self, event_type: str, game_name: str, level_id: str | None,
                   level_name: str | None, x_position: int | None,
                   details: dict[str, Any] | None = None) -> dict[str, Any]:
        from core.tracking_service import record_event
        return record_event(event_type=event_type, game_name=game_name,
                            level_id=level_id, level_name=level_name,
                            x_position=x_position, details=details,
                            user_id=self.user_id)

    def record_split(self, session_id: int, game_name: str, level_id: str,
                     level_name: str | None, split_ms: int, entered_at: float,
                     exited_at: float, death_count: int = 0,
                     best_x: int | None = None) -> dict[str, Any]:
        from core.splits_service import record_split
        return record_split(session_id=session_id, game_name=game_name,
                            level_id=level_id, level_name=level_name,
                            split_ms=split_ms, entered_at=entered_at,
                            exited_at=exited_at, death_count=death_count,
                            best_x=best_x)


class HttpApiClient(TrackerClient):
    def __init__(self, base_url: str = "http://127.0.0.1:8000",
                 user_id: int | None = None) -> None:
        super().__init__(user_id=user_id)
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"

    def get_current_session(self) -> dict[str, Any]:
        r = self._session.get(f"{self.base_url}/session/current", timeout=5)
        r.raise_for_status()
        return r.json()

    def stop_session(self) -> dict[str, Any]:
        r = self._session.post(f"{self.base_url}/session/stop", timeout=5)
        r.raise_for_status()
        return r.json()

    def post_progress(self, game_name: str, level_id: str | None,
                      level_name: str | None, x_position: int | None) -> dict[str, Any]:
        r = self._session.post(f"{self.base_url}/tracking/progress",
            json={"game_name": game_name, "level_id": level_id,
                  "level_name": level_name, "x_position": x_position}, timeout=5)
        r.raise_for_status()
        return r.json()

    def post_event(self, event_type: str, game_name: str, level_id: str | None,
                   level_name: str | None, x_position: int | None,
                   details: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self._session.post(f"{self.base_url}/tracking/event",
            json={"event_type": event_type, "game_name": game_name,
                  "level_id": level_id, "level_name": level_name,
                  "x_position": x_position, "details": details or {}}, timeout=5)
        r.raise_for_status()
        return r.json()

    def record_split(self, session_id: int, game_name: str, level_id: str,
                     level_name: str | None, split_ms: int, entered_at: float,
                     exited_at: float, death_count: int = 0,
                     best_x: int | None = None) -> dict[str, Any]:
        r = self._session.post(f"{self.base_url}/tracking/split",
            json={"session_id": session_id, "game_name": game_name,
                  "level_id": level_id, "level_name": level_name,
                  "split_ms": split_ms, "entered_at": entered_at,
                  "exited_at": exited_at, "death_count": death_count,
                  "best_x": best_x}, timeout=5)
        r.raise_for_status()
        return r.json()
