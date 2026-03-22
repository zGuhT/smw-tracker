"""
Detect whether a ROM is an SMW hack.

Three-layer detection:
1. ROM header: exact "SUPER MARIOWORLD" match (with exclusion list)
2. Filename keywords (broad with explicit exclusions for non-SMW Mario games)
3. SMW engine RAM check (delayed — only reliable after game has initialized)

The detector supports retrying: on first check it may not have engine data,
so it marks the result as "uncertain" and re-checks after a delay.
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

ROM_HEADER_TITLE_ADDR = 0x00FFC0
ROM_HEADER_TITLE_SIZE = 21

# Game mode and SMW-specific RAM
GAME_MODE_ADDR = 0xF50100
TRANSLEVEL_ADDR = 0xF513BF
BONUS_GAME_ADDR = 0xF50DB3

# ── Exact ROM header titles that ARE SMW ──
SMW_EXACT_HEADERS = {
    "SUPER MARIOWORLD",
    "SUPER MARIO WORLD",
}

# ── ROM header titles that are NOT SMW ──
NOT_SMW_HEADERS = {
    "SUPER MARIO KART",
    "SUPER MARIO RPG",
    "SUPER MARIO ALLSTARS", "SUPER MARIO ALL-STARS", "SUPER MARIO ALL STARS",
    "SUPER MARIOALLSTARS",
    "YOSHI'S ISLAND", "YOSHIS ISLAND", "YOSSY'S ISLAND",
    "SUPER MARIO WORLD 2",
    "MARIO PAINT",
    "MARIO IS MISSING",
    "MARIO'S TIME MACHINE",
    "HOTEL MARIO",
    "SUPER MARIO COLLECTION",
    "MARIO & WARIO",
    "MARIO'S EARLY YEARS",
    "MARIO'S SUPER PICROSS",
    "SUPER MARIO ALL",
}

# ── Filename keywords that CONFIRM SMW ──
SMW_FILENAME_KEYWORDS = {
    # Exact game references
    "super mario world", "super marioworld",
    # Engine/hack terms
    "kaizo",
    "smw",
    # Specific well-known hacks
    "grand poo world", "gpw",
    "quickie world",
    "pit of despair",
    "invictus",
    "dram world",
    "item abuse",
    "super moo world",
    "sweet shell", "sweetshell",
    "love yourself",
    "learn 2 kaizo",
    "vanilla cape",
    "storks and apes",
    "celery",
    "akogare",
    "playground kaizo",
    "rom hack",
    "barb",
    "oops! all",
    "fortresses",
    "add world",
    "supercindy", "cindy world",
}

# ── Filename keywords that EXCLUDE SMW ──
NOT_SMW_FILENAMES = {
    "mario kart", "super mario kart",
    "mario rpg", "mario's rpg",
    "all-stars", "all stars", "allstars",
    "yoshi's island", "yoshis island",
    "mario paint",
    "mario is missing",
    "time machine",
    "mario & wario",
    "super mario world 2",
    "mario's early",
    "mario's super picross", "picross",
    "mario party",
    "dr. mario", "dr mario",
}


class SMWDetector:
    def __init__(self) -> None:
        self._cache: dict[str, bool | None] = {}  # None = uncertain, needs retry
        self._cache_time: dict[str, float] = {}
        self._retry_after = 3.0  # seconds before retrying uncertain results

    def detect(self, rom_path: str | None, game_name: str | None,
               qusb: Any = None) -> bool:
        if not rom_path and not game_name:
            return False

        cache_key = rom_path or game_name or ""
        now = time.time()

        # Check cache — but retry uncertain results after delay
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if cached is not None:
                return cached
            # Uncertain — retry if enough time passed
            if now - self._cache_time.get(cache_key, 0) < self._retry_after:
                return False  # Default to non-SMW while uncertain
            # Time to retry

        result = None
        method = "none"

        # Check filename exclusions first
        if game_name and self._is_excluded_filename(game_name):
            result = False
            method = "excluded_filename"

        # Method 1: ROM header
        if result is None and qusb:
            try:
                header = self._read_header_title(qusb)
                if header:
                    if self._is_excluded_header(header):
                        result = False
                        method = f"excluded_header:'{header.strip()}'"
                    elif self._is_smw_header(header):
                        result = True
                        method = f"header:'{header.strip()}'"
            except Exception as exc:
                log.debug("Header read failed: %s", exc)

        # Method 2: Filename keywords
        if result is None and game_name:
            if self._check_filename(game_name):
                result = True
                method = f"filename:'{game_name}'"

        # Method 3: Engine RAM check (only if still uncertain)
        if result is None and qusb:
            try:
                engine_result = self._check_smw_engine(qusb)
                if engine_result is True:
                    result = True
                    method = "smw_engine_ram"
                elif engine_result is False:
                    result = False
                    method = "engine_ram_negative"
                # else None = inconclusive, mark uncertain
            except Exception:
                pass

        # Store result
        self._cache[cache_key] = result
        self._cache_time[cache_key] = now

        if result is True:
            log.info("SMW detected [%s] for %s", method, game_name or rom_path)
        elif result is False:
            log.info("Not SMW [%s]: %s", method, game_name or rom_path)
        else:
            log.info("SMW uncertain for %s, will retry in %.0fs", game_name or rom_path, self._retry_after)

        return result is True

    def _read_header_title(self, qusb: Any) -> str | None:
        data = qusb.read_block(ROM_HEADER_TITLE_ADDR, ROM_HEADER_TITLE_SIZE)
        if not data or len(data) < ROM_HEADER_TITLE_SIZE:
            return None
        return "".join(chr(b) if 0x20 <= b <= 0x7E else " " for b in data)

    def _is_smw_header(self, title: str) -> bool:
        upper = title.upper().strip()
        return any(upper == h or upper.startswith(h) for h in SMW_EXACT_HEADERS)

    def _is_excluded_header(self, title: str) -> bool:
        upper = title.upper().strip()
        return any(excl in upper for excl in NOT_SMW_HEADERS)

    def _is_excluded_filename(self, game_name: str) -> bool:
        lower = game_name.lower().replace("_", " ")
        return any(kw in lower for kw in NOT_SMW_FILENAMES)

    def _check_filename(self, game_name: str | None) -> bool:
        if not game_name:
            return False
        lower = game_name.lower().replace("_", " ")
        if any(kw in lower for kw in NOT_SMW_FILENAMES):
            return False
        return any(kw in lower for kw in SMW_FILENAME_KEYWORDS)

    def _check_smw_engine(self, qusb: Any) -> bool | None:
        """
        Check SMW engine RAM patterns.
        Returns True (SMW), False (definitely not), or None (inconclusive).
        """
        try:
            game_mode = qusb.read_u8(GAME_MODE_ADDR)

            # During SNES boot/reset, RAM is indeterminate — inconclusive
            if game_mode == 0x55 or game_mode == 0xFF:
                return None

            # SMW game modes are 0x00-0x19 (with some hacks adding up to ~0x20)
            if game_mode > 0x30:
                return False

            translevel = qusb.read_u8(TRANSLEVEL_ADDR)
            bonus = qusb.read_u8(BONUS_GAME_ADDR)

            # SMW: translevel 0x00-0x60, bonus flag 0 or 1
            if translevel <= 0x60 and bonus <= 0x01:
                return True

            # Values outside SMW range suggest non-SMW
            if translevel > 0x80 or bonus > 0x10:
                return False

            return None  # Inconclusive
        except Exception:
            return None

    def clear_cache(self) -> None:
        self._cache.clear()
        self._cache_time.clear()
