"""Streamlit-dashboard companion endpoints — THROWAWAY.

The old /prototype/dashboard variants (A/B/C) were retired when the day
browser became the real UI (heimdall/api/ui.py, served at GET /). This
module now only backs the throwaway streamlit probe (prototype_streamlit.py)
with its live media stream; delete together with that probe.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

prototype_router = APIRouter()


@prototype_router.get("/prototype/stream")
def prototype_stream(request: Request) -> dict:
    """Live extension media stream (v2 #44) — THROWAWAY, prototype only."""
    try:
        db = request.app.state.db
        rows = db.latest_media_stream()
        return {"total": len(rows), "items": rows}
    except Exception:  # noqa: BLE001
        return {"total": 0, "items": []}

