"""ROM path cleaning, title normalization, and similarity matching."""
from __future__ import annotations

import os
import re
from pathlib import Path


def clean_rom_path(rom_path: str | None) -> str | None:
    if not rom_path:
        return None
    cleaned = rom_path.replace("\x00", "").strip()
    return cleaned or None


def rom_filename_from_path(rom_path: str | None) -> str | None:
    cleaned = clean_rom_path(rom_path)
    if not cleaned:
        return None
    return os.path.basename(cleaned)


def rom_stem_from_path(rom_path: str | None) -> str | None:
    filename = rom_filename_from_path(rom_path)
    if not filename:
        return None
    return Path(filename).stem


def normalize_title(title: str | None) -> str | None:
    if not title:
        return None

    t = title.strip()
    t = re.sub(r"\[[^\]]*\]", "", t)           # [region tags]
    t = re.sub(r"\([^)]*\)", "", t)             # (version info)
    # Version patterns: v1.0, v2, 1.0, etc
    t = re.sub(r"\bv\d+(\.\d+)*\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b\d+\.\d+\b", "", t)         # standalone 1.0, 2.1 etc
    t = re.sub(r"\b(final|beta|demo)\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\brev\s*[A-Z0-9]+\b", "", t, flags=re.IGNORECASE)
    t = t.replace("_", " ")
    t = re.sub(r"\s*[-:]+\s*$", "", t)          # trailing separators
    t = re.sub(r"\s+", " ", t).strip()

    return t or None


def _tokenize(s: str) -> set[str]:
    """Split a title into lowercase word tokens for comparison."""
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def title_similarity(a: str, b: str) -> float:
    """
    Simple Jaccard similarity between two titles.
    Returns 0.0 to 1.0 where 1.0 is identical token sets.
    """
    tokens_a = _tokenize(a)
    tokens_b = _tokenize(b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def build_title_candidates(rom_path: str | None) -> list[str]:
    """Generate progressively simpler title strings to try for metadata lookup."""
    stem = rom_stem_from_path(rom_path)
    if not stem:
        return []

    candidates: list[str] = []
    raw = stem.strip()
    norm = normalize_title(raw)

    if raw:
        candidates.append(raw)
    if norm and norm not in candidates:
        candidates.append(norm)

    # Strip leading numeric prefix: "03 - Intermediate - Game" -> "Intermediate - Game"
    stripped = re.sub(r"^\d+\s*[-_]\s*", "", raw).strip()
    stripped = normalize_title(stripped)
    if stripped and stripped not in candidates:
        candidates.append(stripped)

    return candidates
