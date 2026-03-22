from __future__ import annotations

from fastapi import APIRouter, Query

from core.metadata_service import fetch_metadata_for_rom

router = APIRouter(prefix="/metadata", tags=["metadata"])


@router.get("/lookup")
def metadata_lookup(rom_path: str = Query(...)):
    return fetch_metadata_for_rom(rom_path)
