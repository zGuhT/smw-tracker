"""
Game metadata lookup: cache → manual overrides → TheGamesDB API → fallback.
Extracts rich data: boxart, screenshots, fanart, overview, genres, developer, publisher, etc.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import requests

from core import db
from core.rom_utils import (
    build_title_candidates,
    clean_rom_path,
    normalize_title,
    rom_stem_from_path,
    title_similarity,
)
from core.time_utils import utc_now_iso

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
OVERRIDES_PATH = BASE_DIR / "data" / "game_overrides.json"

TGDB_API_BASE = "https://api.thegamesdb.net/v1"
TGDB_API_KEY = "4e104111f062a050ff189febbe79e93a653eeb5fe9d4bbf599f16038b4fe7350"
TGDB_SNES_PLATFORM_ID = 6
MATCH_SIMILARITY_THRESHOLD = 0.55


def load_overrides() -> dict[str, Any]:
    if not OVERRIDES_PATH.exists():
        return {}
    with OVERRIDES_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_tgdb_api_key() -> str:
    return os.getenv("TGDB_API_KEY", TGDB_API_KEY)


def get_cached_metadata_by_rom_name(rom_name: str) -> dict[str, Any] | None:
    return db.fetchone(
        "SELECT * FROM game_metadata WHERE rom_name = ? ORDER BY id DESC LIMIT 1",
        (rom_name,),
    )


def get_metadata_by_game_name(game_name: str) -> dict[str, Any] | None:
    return db.fetchone(
        "SELECT * FROM game_metadata WHERE rom_name = ? ORDER BY id DESC LIMIT 1",
        (game_name,),
    )


def get_all_game_metadata() -> list[dict[str, Any]]:
    return db.fetchall(
        "SELECT * FROM game_metadata GROUP BY rom_name ORDER BY display_name"
    )


def save_metadata(
    rom_path: str | None,
    rom_name: str,
    normalized_name: str,
    platform_name: str,
    source: str,
    external_game_id: str | None = None,
    display_name: str | None = None,
    overview: str | None = None,
    genres: list[str] | None = None,
    release_date: str | None = None,
    developer: str | None = None,
    publisher: str | None = None,
    players: str | None = None,
    rating: str | None = None,
    boxart_url: str | None = None,
    screenshot_url: str | None = None,
    fanart_url: str | None = None,
    banner_url: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now_iso()
    db.execute("DELETE FROM game_metadata WHERE rom_name = ?", (rom_name,))
    metadata_id = db.insert_returning_id(
        """
        INSERT INTO game_metadata (
            rom_path, rom_name, normalized_name, platform_name, source,
            external_game_id, display_name, overview, genres_json,
            release_date, developer, publisher, players, rating,
            boxart_url, screenshot_url, fanart_url, banner_url,
            raw_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rom_path, rom_name, normalized_name, platform_name, source,
            external_game_id, display_name, overview, json.dumps(genres or []),
            release_date, developer, publisher, players, rating,
            boxart_url, screenshot_url, fanart_url, banner_url,
            json.dumps(raw_payload or {}), now, now,
        ),
    )
    db.commit()
    return db.fetchone("SELECT * FROM game_metadata WHERE id = ?", (metadata_id,)) or {}


def try_override_lookup(rom_name: str) -> dict[str, Any] | None:
    overrides = load_overrides()
    if rom_name not in overrides:
        return None
    entry = overrides[rom_name]
    return {
        "rom_name": rom_name,
        "normalized_name": normalize_title(rom_name) or rom_name,
        "platform_name": entry.get("platform_name", "Super Nintendo (SNES)"),
        "source": entry.get("source", "manual"),
        "external_game_id": entry.get("external_game_id"),
        "display_name": entry.get("display_name", rom_name),
        "overview": entry.get("overview"),
        "genres": entry.get("genres_json", []),
        "release_date": entry.get("release_date"),
        "developer": entry.get("developer"),
        "publisher": entry.get("publisher"),
        "players": entry.get("players"),
        "rating": entry.get("rating"),
        "boxart_url": entry.get("boxart_url"),
        "screenshot_url": entry.get("screenshot_url"),
        "fanart_url": entry.get("fanart_url"),
        "banner_url": entry.get("banner_url"),
        "raw_payload": entry,
    }


# ── TGDB API calls ──

def search_tgdb_by_name(title: str, platform_id: int | None = None) -> dict[str, Any] | None:
    api_key = get_tgdb_api_key()
    if not api_key:
        return None

    params: dict[str, Any] = {
        "apikey": api_key,
        "name": title,
        "include": "boxart",
    }
    if platform_id is not None:
        params["filter[platform]"] = platform_id

    try:
        response = requests.get(f"{TGDB_API_BASE}/Games/ByGameName", params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()

        data = payload.get("data", {})
        games = data.get("games") if isinstance(data, dict) else None
        if (not games) and platform_id is not None:
            log.info("No results for '%s' with platform=%s, retrying without filter", title, platform_id)
            params.pop("filter[platform]", None)
            response = requests.get(f"{TGDB_API_BASE}/Games/ByGameName", params=params, timeout=10)
            response.raise_for_status()
            payload = response.json()

        return payload
    except Exception as exc:
        log.warning("TGDB search failed for '%s': %s", title, exc)
        return None


def fetch_tgdb_images(game_id: int | str) -> dict[str, Any] | None:
    api_key = get_tgdb_api_key()
    if not api_key:
        return None
    try:
        response = requests.get(
            f"{TGDB_API_BASE}/Games/Images",
            params={"apikey": api_key, "games_id": str(game_id)},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        log.warning("TGDB image fetch failed for game %s: %s", game_id, exc)
        return None


def fetch_tgdb_game_detail(game_id: int | str) -> dict[str, Any] | None:
    """Fetch full game details by ID to get developers, publishers, genres by name."""
    api_key = get_tgdb_api_key()
    if not api_key:
        return None
    try:
        response = requests.get(
            f"{TGDB_API_BASE}/Games/ByGameID",
            params={
                "apikey": api_key,
                "id": str(game_id),
                "fields": "players,publishers,genres,overview,rating",
                "include": "boxart",
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        log.warning("TGDB detail fetch failed for game %s: %s", game_id, exc)
        return None


# ── Result parsing ──

def select_best_tgdb_match(payload: dict[str, Any], search_term: str) -> dict[str, Any] | None:
    if not payload:
        return None
    data = payload.get("data")
    if not data or not isinstance(data, dict):
        return None
    games = data.get("games")
    if not games or not isinstance(games, list):
        return None

    best_match = None
    best_score = 0.0

    for game in games:
        game_title = game.get("game_title", "")
        score = title_similarity(search_term, game_title)
        if score > best_score:
            best_score = score
            best_match = game

    if best_match and best_score >= MATCH_SIMILARITY_THRESHOLD:
        log.info("TGDB match: '%s' -> '%s' (score=%.2f)", search_term, best_match.get("game_title"), best_score)
        return best_match

    if best_match:
        log.info("TGDB REJECTED: '%s' -> '%s' (score=%.2f)", search_term, best_match.get("game_title"), best_score)
    return None


def extract_image_urls(payload: dict[str, Any], game_id: int | str | None) -> dict[str, str | None]:
    """Extract all image URLs from a TGDB response."""
    result: dict[str, str | None] = {
        "boxart_url": None, "screenshot_url": None,
        "fanart_url": None, "banner_url": None,
    }
    if not payload or game_id is None:
        return result

    base_url = "https://cdn.thegamesdb.net/images/original/"
    str_id = str(game_id)
    image_entries: list[dict] = []

    # Search response: include.boxart.base_url + include.boxart.data.{id}
    include = payload.get("include", {})
    if isinstance(include, dict):
        boxart_section = include.get("boxart", {})
        if isinstance(boxart_section, dict):
            bu = boxart_section.get("base_url", {})
            if isinstance(bu, dict) and "original" in bu:
                base_url = bu["original"]
            boxart_data = boxart_section.get("data", {})
            if isinstance(boxart_data, dict):
                entries = boxart_data.get(str_id, [])
                if isinstance(entries, list):
                    image_entries.extend(entries)

    # Images endpoint: data.base_url + data.images.{id}
    data = payload.get("data", {})
    if isinstance(data, dict):
        bu = data.get("base_url", {})
        if isinstance(bu, dict) and "original" in bu:
            base_url = bu["original"]
        imgs = data.get("images", {})
        if isinstance(imgs, dict):
            entries = imgs.get(str_id, [])
            if isinstance(entries, list):
                image_entries.extend(entries)

    for entry in image_entries:
        if not isinstance(entry, dict):
            continue
        filename = entry.get("filename")
        if not filename:
            continue

        img_type = entry.get("type", "").lower()
        side = entry.get("side", "").lower()
        url = f"{base_url}{filename.lstrip('/')}"

        if not result["boxart_url"] and ("boxart" in img_type or "front" in side):
            result["boxart_url"] = url
        if not result["screenshot_url"] and "screenshot" in img_type:
            result["screenshot_url"] = url
        if not result["fanart_url"] and "fanart" in img_type:
            result["fanart_url"] = url
        if not result["banner_url"] and ("banner" in img_type or "graphical" in img_type):
            result["banner_url"] = url

    return result


def extract_extra_details(game_data: dict[str, Any]) -> dict[str, str | None]:
    """Extract developer, publisher, players, rating from a game record."""
    details: dict[str, str | None] = {
        "developer": None, "publisher": None, "players": None, "rating": None,
    }

    developers = game_data.get("developers", [])
    if isinstance(developers, list) and developers:
        details["developer"] = ", ".join(str(d) for d in developers)

    publishers = game_data.get("publishers", [])
    if isinstance(publishers, list) and publishers:
        details["publisher"] = ", ".join(str(p) for p in publishers)

    players_val = game_data.get("players")
    if players_val is not None:
        details["players"] = str(players_val)

    rating_val = game_data.get("rating")
    if rating_val is not None:
        details["rating"] = str(rating_val)

    return details


# ── Main lookup ──

def fetch_metadata_for_rom(rom_path: str | None) -> dict[str, Any]:
    cleaned_rom_path = clean_rom_path(rom_path)
    rom_name = rom_stem_from_path(cleaned_rom_path) or "Unknown Game"
    normalized_name = normalize_title(rom_name) or rom_name

    # 1. Cache
    cached = get_cached_metadata_by_rom_name(rom_name)
    if cached:
        return cached

    # 2. Manual overrides
    override = try_override_lookup(rom_name)
    if override:
        return save_metadata(
            rom_path=cleaned_rom_path, rom_name=rom_name,
            normalized_name=override["normalized_name"],
            platform_name=override["platform_name"], source=override["source"],
            external_game_id=override.get("external_game_id"),
            display_name=override["display_name"], overview=override.get("overview"),
            genres=override.get("genres"), release_date=override.get("release_date"),
            developer=override.get("developer"), publisher=override.get("publisher"),
            players=override.get("players"), rating=override.get("rating"),
            boxart_url=override.get("boxart_url"), screenshot_url=override.get("screenshot_url"),
            fanart_url=override.get("fanart_url"), banner_url=override.get("banner_url"),
            raw_payload=override.get("raw_payload"),
        )

    # 3. TheGamesDB lookup
    for candidate in build_title_candidates(cleaned_rom_path):
        payload = search_tgdb_by_name(candidate, platform_id=TGDB_SNES_PLATFORM_ID)
        if not payload:
            continue

        best = select_best_tgdb_match(payload, search_term=candidate)
        if not best:
            continue

        game_id = best.get("id")
        display_name = best.get("game_title") or candidate
        overview = best.get("overview")
        release_date = best.get("release_date")
        genres = [str(x) for x in best["genres"]] if isinstance(best.get("genres"), list) else []

        # Extract extra details from game data
        extra = extract_extra_details(best)

        # Get images from search include
        images = extract_image_urls(payload, game_id)

        # If no images from search, try dedicated Images endpoint
        if not images["boxart_url"] and game_id:
            img_payload = fetch_tgdb_images(game_id)
            if img_payload:
                images = extract_image_urls(img_payload, game_id)

        log.info("Saving TGDB: rom='%s' display='%s' boxart=%s", rom_name, display_name, bool(images["boxart_url"]))

        return save_metadata(
            rom_path=cleaned_rom_path, rom_name=rom_name,
            normalized_name=normalized_name, platform_name="Super Nintendo (SNES)",
            source="thegamesdb",
            external_game_id=str(game_id) if game_id is not None else None,
            display_name=display_name, overview=overview, genres=genres,
            release_date=release_date,
            developer=extra["developer"], publisher=extra["publisher"],
            players=extra["players"], rating=extra["rating"],
            boxart_url=images["boxart_url"], screenshot_url=images["screenshot_url"],
            fanart_url=images["fanart_url"], banner_url=images["banner_url"],
            raw_payload=payload,
        )

    # 4. Fallback
    log.info("No TGDB match for '%s', saving fallback", rom_name)
    return save_metadata(
        rom_path=cleaned_rom_path, rom_name=rom_name,
        normalized_name=normalized_name, platform_name="Super Nintendo (SNES)",
        source="fallback", display_name=rom_name,
    )
