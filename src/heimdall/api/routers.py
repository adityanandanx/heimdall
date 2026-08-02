"""HTTP routers: health, search, frames, pipes, status.

All responses are JSON with snake_case fields; errors use FastAPI's
{"detail": ...} convention. Loopback-only bind is the security boundary.
"""

from __future__ import annotations

import sqlite3
import time

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from heimdall import __version__
from heimdall.config import Config
from heimdall.pipes.core import UnknownPipeError, registered_pipes, run_pipe
from heimdall.timeutil import day_bounds, iso_to_ms, today_str

health_router = APIRouter()
search_router = APIRouter()
frames_router = APIRouter()
pipes_router = APIRouter()
status_router = APIRouter()

MAX_LIMIT = 100
DEFAULT_LIMIT = 20


def _page(limit: int, offset: int) -> tuple[int, int]:
    if limit < 1 or offset < 0:
        raise HTTPException(status_code=422, detail="limit >= 1 and offset >= 0 required")
    return min(limit, MAX_LIMIT), offset


def _parse_time(value: str | None, name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return iso_to_ms(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid {name}: {value!r}")


def _db(request: Request) -> object:
    return request.app.state.db


@health_router.get("/health")
def health(request: Request) -> dict:
    db = _db(request)
    try:
        conn = db.open()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        db_ok = "ok"
    except sqlite3.Error:
        db_ok = "error"
    return {
        "status": "ok",
        "version": __version__,
        "db": db_ok,
        "uptime_s": round(time.time() - request.app.state.started),
    }


@search_router.get("/search")
def search(
    request: Request,
    q: str = Query(..., min_length=1),
    window_class: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    offset: int = Query(0, ge=0),
) -> dict:
    limit, offset = _page(limit, offset)
    start_ms = _parse_time(start, "start")
    end_ms = _parse_time(end, "end")
    try:
        total, items = _db(request).search(
            q, window_class=window_class, start=start_ms, end=end_ms,
            limit=limit, offset=offset,
        )
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=422, detail=f"invalid search query: {exc}")
    return {"total": total, "items": items}


@frames_router.get("/frames")
def list_frames(
    request: Request,
    window_class: str | None = None,
    trigger: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    offset: int = Query(0, ge=0),
) -> dict:
    limit, offset = _page(limit, offset)
    start_ms = _parse_time(start, "start")
    end_ms = _parse_time(end, "end")
    total, items = _db(request).list_frames(
        window_class=window_class, trigger=trigger, start=start_ms, end=end_ms,
        limit=limit, offset=offset,
    )
    return {"total": total, "items": items}


@frames_router.get("/frames/{frame_id}")
def frame_detail(request: Request, frame_id: int) -> dict:
    frame = _db(request).get_frame(frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail=f"frame {frame_id} not found")
    return frame


@frames_router.get("/frames/{frame_id}/image")
def frame_image(request: Request, frame_id: int):
    frame = _db(request).get_frame(frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail=f"frame {frame_id} not found")
    image = request.app.state.config.data_path / frame["image_path"]
    if not image.exists():
        raise HTTPException(status_code=404, detail="image file is missing")
    return FileResponse(image, media_type="image/jpeg")


@pipes_router.get("/pipes")
def list_pipes() -> dict:
    return {"names": registered_pipes()}


@pipes_router.post("/pipes/run/{name}")
def run_pipe_endpoint(request: Request, name: str, day: str | None = None) -> dict:
    config: Config = request.app.state.config
    resolved_day = today_str() if day is None else day
    try:
        result = run_pipe(
            name,
            day=resolved_day,
            config=config,
            db_path=request.app.state.db_path,
            llm=request.app.state.llm,
        )
    except UnknownPipeError:
        raise HTTPException(status_code=404, detail=f"unknown pipe {name!r}")
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    request.app.state.last_runs[name] = result["ts"]
    return result


@status_router.get("/status")
def status(request: Request) -> dict:
    app = request.app
    config: Config = app.state.config
    now_ms = int(time.time() * 1000)
    start_ms, end_ms = day_bounds(today_str())
    today = app.state.db.count_frames(start_ms, end_ms)

    heartbeat = config.data_path / "capture.heartbeat"
    alive = False
    last_event_ms = None
    if heartbeat.exists():
        try:
            last_event_ms = int(heartbeat.read_text().strip())
        except ValueError:
            last_event_ms = None
        grace = config.capture.keepalive_min * 60_000 * 3
        alive = last_event_ms is not None and (now_ms - last_event_ms) < grace

    llama_reachable = _llama_reachable(config.llama_server.base_url, app.state.transport)

    return {
        "server": {
            "status": "ok",
            "version": __version__,
            "uptime_s": round(time.time() - app.state.started),
        },
        "db": {"frames_today": today, "size_bytes": app.state.db.size_bytes()},
        "capture": {"alive": alive, "last_event_ts": last_event_ms},
        "llama": {"reachable": llama_reachable},
        "pipes": {"last_runs": {name: app.state.last_runs.get(name) for name in registered_pipes()}},
    }


def _llama_reachable(base_url: str, transport: httpx.AsyncBaseTransport | None) -> bool:
    try:
        with httpx.Client(base_url=base_url, timeout=2.0, transport=transport or httpx.HTTPTransport()) as c:
            r = c.get("/health")
            return r.status_code == 200
    except Exception:
        return False
