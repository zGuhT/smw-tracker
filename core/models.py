"""Pydantic request/response models for the API layer."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# --- Session ---

class SessionStartRequest(BaseModel):
    game_name: str = Field(..., min_length=1)
    platform: str = "SNES"


class SessionStopResponse(BaseModel):
    success: bool


class SessionCurrentResponse(BaseModel):
    id: int | None = None
    game_name: str | None = None
    platform: str | None = None
    start_time: str | None = None
    duration_seconds: int | None = None
    is_active: bool = False
    current_level_id: str | None = None
    current_level_name: str | None = None
    current_x_position: int | None = None
    deaths_this_session: int = 0


# --- Tracking ---

class TrackingEventRequest(BaseModel):
    event_type: str = Field(..., min_length=1)
    game_name: str = Field(..., min_length=1)
    level_id: str | None = None
    level_name: str | None = None
    x_position: int | None = None
    details: dict[str, Any] | None = None


class ProgressSnapshotRequest(BaseModel):
    game_name: str = Field(..., min_length=1)
    level_id: str | None = None
    level_name: str | None = None
    x_position: int | None = None


# --- Stats ---

class MostPlayedItem(BaseModel):
    game_name: str
    total_playtime_seconds: int
    session_count: int


class PlaytimeTrendItem(BaseModel):
    date: str
    total_playtime_seconds: int


class SessionsPerDayItem(BaseModel):
    date: str
    session_count: int


# --- Metadata ---

class CurrentGameMetadataResponse(BaseModel):
    rom_name: str | None = None
    display_name: str | None = None
    platform_name: str | None = None
    source: str | None = None
    external_game_id: str | None = None
    overview: str | None = None
    release_date: str | None = None
    boxart_url: str | None = None
    screenshot_url: str | None = None
