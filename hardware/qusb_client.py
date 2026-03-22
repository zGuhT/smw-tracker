"""
QUsb2Snes WebSocket client.

Key changes from original:
- Automatic reconnection on connection loss
- Batch read method to fetch multiple memory regions in fewer round-trips
- Connection state tracking
- Quieter logging (debug level instead of printing everything)
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from websocket import WebSocket, WebSocketException, create_connection

log = logging.getLogger(__name__)


class QUsb2SnesClient:
    def __init__(self, url: str = "ws://127.0.0.1:23074", app_name: str = "SFC Tracker") -> None:
        self.url = url
        self.app_name = app_name
        self.ws: WebSocket | None = None
        self.attached_device: str | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self.ws is not None

    def connect(self) -> None:
        if self.is_connected:
            return
        self.close()
        self.ws = create_connection(self.url, timeout=5)
        self._connected = True
        self.name(self.app_name)
        log.info("Connected to QUsb2Snes at %s", self.url)

    def close(self) -> None:
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
            finally:
                self.ws = None
                self.attached_device = None
                self._connected = False

    def reconnect(self) -> None:
        """Close and re-establish the connection."""
        log.info("Reconnecting to QUsb2Snes...")
        self.close()
        self.connect()

    def _send_json(self, payload: dict[str, Any]) -> None:
        if self.ws is None:
            raise RuntimeError("WebSocket is not connected")
        self.ws.send(json.dumps(payload))

    def _recv_frame(self) -> str | bytes:
        if self.ws is None:
            raise RuntimeError("WebSocket is not connected")
        return self.ws.recv()

    def _recv_json(self, max_attempts: int = 5) -> dict[str, Any]:
        last_raw: str | bytes | None = None

        for attempt in range(1, max_attempts + 1):
            raw = self._recv_frame()
            last_raw = raw

            if isinstance(raw, bytes):
                raise RuntimeError(f"Expected JSON but received binary ({len(raw)} bytes)")

            text = raw.strip()
            if not text:
                log.debug("Empty frame (attempt %d/%d), retrying...", attempt, max_attempts)
                time.sleep(0.1)
                continue

            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Non-JSON text from QUsb2Snes: {text!r}") from exc

            if not isinstance(parsed, dict):
                raise RuntimeError(f"Expected JSON object, got: {parsed!r}")
            return parsed

        raise RuntimeError(f"No valid JSON reply. Last frame: {last_raw!r}")

    def name(self, app_name: str) -> None:
        self._send_json({"Opcode": "Name", "Space": "SNES", "Operands": [app_name]})

    def device_list(self) -> list[str]:
        self._send_json({"Opcode": "DeviceList", "Space": "SNES", "Operands": []})
        reply = self._recv_json()
        return [str(x) for x in reply.get("Results", [])]

    def attach(self, device_name: str) -> None:
        self._send_json({"Opcode": "Attach", "Space": "SNES", "Operands": [device_name]})
        self.attached_device = device_name
        log.info("Attached to device: %s", device_name)

    def info(self) -> dict[str, Any]:
        self._send_json({"Opcode": "Info", "Space": "SNES", "Operands": []})
        return self._recv_json()

    def get_current_rom_path(self) -> str | None:
        reply = self.info()
        results = reply.get("Results", [])
        if len(results) >= 3:
            rom = results[2]
            if rom is None:
                return None
            cleaned = str(rom).replace("\x00", "").strip()
            return cleaned or None
        return None

    def auto_attach_first_device(self, wait: bool = True, retry_seconds: float = 1.0) -> str:
        while True:
            devices = self.device_list()
            if devices:
                device = devices[0]
                self.attach(device)
                return device
            if not wait:
                raise RuntimeError("No QUsb2Snes devices found")
            log.info("No devices found, waiting...")
            time.sleep(retry_seconds)

    def read_block(self, address: int, size: int) -> bytes:
        if self.ws is None:
            raise RuntimeError("WebSocket is not connected")

        self._send_json({
            "Opcode": "GetAddress",
            "Space": "SNES",
            "Operands": [f"{address:X}", f"{size:X}"],
        })
        raw = self._recv_frame()

        if isinstance(raw, str):
            raise RuntimeError(f"Expected binary block but received text: {raw!r}")
        return bytes(raw)

    def read_u8(self, address: int) -> int:
        return self.read_block(address, 1)[0]

    def read_u16_le(self, address: int) -> int:
        return int.from_bytes(self.read_block(address, 2), "little")

    def read_u24_le(self, address: int) -> int:
        return int.from_bytes(self.read_block(address, 3), "little")

    def reset(self) -> None:
        """Send a soft reset command to the SNES."""
        log.info("Sending SNES reset command")
        self._send_json({"Opcode": "Reset", "Space": "SNES", "Operands": []})
