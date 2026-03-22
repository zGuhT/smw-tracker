"""
Cloud sync client — wraps DirectServiceClient for local writes,
and pushes the full session state to the cloud server in a background thread.

Usage:
    client = CloudSyncClient(cloud_url="https://smwtracker.com", api_key="your-key")
    tracker = SMWTracker(qusb=qusb, client=client)

All TrackerClient methods work locally as before. The background thread
pushes get_current_session_payload() to the cloud every 500ms.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import requests

from hardware.tracker_client import DirectServiceClient, TrackerClient

log = logging.getLogger(__name__)


class CloudSyncClient(TrackerClient):
    """Local-first tracker client with cloud sync."""

    def __init__(
        self,
        cloud_url: str = "https://smwtracker.com",
        api_key: str = "",
        push_interval: float = 0.5,
        user_id: int | None = None,
    ) -> None:
        super().__init__(user_id=user_id)
        self._local = DirectServiceClient(user_id=user_id)
        self._cloud_url = cloud_url.rstrip("/")
        self._api_key = api_key
        self._push_interval = push_interval
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"
        if api_key:
            self._session.headers["Authorization"] = f"Bearer {api_key}"

        self._running = True
        self._force_push = threading.Event()

        # Start background push thread
        self._thread = threading.Thread(target=self._push_loop, daemon=True, name="cloud-sync")
        self._thread.start()
        log.info("Cloud sync started → %s (interval=%.1fs, user_id=%s)",
                 self._cloud_url, self._push_interval, self.user_id)

    # ── TrackerClient interface (all go to local first) ──

    def get_current_session(self) -> dict[str, Any]:
        return self._local.get_current_session()

    def stop_session(self) -> dict[str, Any]:
        result = self._local.stop_session()
        self._force_push.set()  # Push immediately
        return result

    def post_progress(self, game_name: str, level_id: str | None,
                      level_name: str | None, x_position: int | None) -> dict[str, Any]:
        return self._local.post_progress(game_name, level_id, level_name, x_position)

    def post_event(self, event_type: str, game_name: str, level_id: str | None,
                   level_name: str | None, x_position: int | None,
                   details: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self._local.post_event(event_type, game_name, level_id, level_name,
                                         x_position, details)
        # Push immediately for important events
        if event_type in ("death", "run_start", "run_pause", "run_resume", "level_enter", "exit"):
            self._force_push.set()
        return result

    def record_split(self, session_id: int, game_name: str, level_id: str,
                     level_name: str | None, split_ms: int, entered_at: float,
                     exited_at: float, death_count: int = 0,
                     best_x: int | None = None) -> dict[str, Any]:
        result = self._local.record_split(session_id, game_name, level_id, level_name,
                                           split_ms, entered_at, exited_at, death_count, best_x)
        self._force_push.set()  # Splits always push immediately
        return result

    # ── Background push loop ──

    def _push_loop(self) -> None:
        """Push the full session state to the cloud every push_interval seconds."""
        push_url = f"{self._cloud_url}/live/push"
        consecutive_errors = 0
        last_payload_hash: int | None = None

        while self._running:
            try:
                # Wait for interval or force push
                self._force_push.wait(timeout=self._push_interval)
                self._force_push.clear()

                # Get the full session payload (same as what the UI polls)
                from core.session_service import get_current_session_payload
                payload = get_current_session_payload()

                # Skip push if payload hasn't changed (reduces bandwidth)
                payload_hash = hash(json.dumps(payload, sort_keys=True, default=str))
                if payload_hash == last_payload_hash and consecutive_errors == 0:
                    continue

                # Push to cloud
                resp = self._session.post(push_url, json=payload, timeout=5)
                if resp.status_code == 200:
                    if consecutive_errors > 0:
                        log.info("Cloud sync restored after %d errors", consecutive_errors)
                    consecutive_errors = 0
                    last_payload_hash = payload_hash
                elif resp.status_code == 401:
                    log.error("Cloud push rejected: invalid API key")
                    consecutive_errors += 1
                else:
                    consecutive_errors += 1
                    if consecutive_errors <= 3:
                        log.warning("Cloud push failed: %s %s", resp.status_code, resp.text[:100])

            except requests.ConnectionError:
                consecutive_errors += 1
                if consecutive_errors == 1:
                    log.warning("Cloud unreachable, will retry...")
                # Exponential backoff: 1s, 2s, 4s, ... up to 30s
                if consecutive_errors > 3:
                    backoff = min(30, 2 ** (consecutive_errors - 3))
                    time.sleep(backoff)
            except Exception as exc:
                consecutive_errors += 1
                if consecutive_errors <= 3:
                    log.warning("Cloud sync error: %s", exc)

    def stop(self) -> None:
        """Stop the sync thread and push final state."""
        self._running = False
        self._force_push.set()
        # Wait briefly for the thread to do a final push
        self._thread.join(timeout=2.0)
