"""HTTP routers: health, search, frames, pipes, status.

All responses are JSON with snake_case fields; errors use FastAPI's
{"detail": ...} convention. Loopback-only bind is the security boundary.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
import uuid
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from heimdall import __version__
from heimdall.config import Config
from heimdall.observability import trace_gate
from heimdall.pipes.core import UnknownPipeError, registered_pipes, run_pipe
from heimdall.timeutil import day_bounds, iso_to_ms, today_str, ts_to_iso

health_router = APIRouter()
search_router = APIRouter()
frames_router = APIRouter()
pipes_router = APIRouter()
status_router = APIRouter()
capture_router = APIRouter()
sessions_router = APIRouter()

MAX_LIMIT = 100
DEFAULT_LIMIT = 20


def _paginate(limit: int, offset: int) -> tuple[int, int]:
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


def _iso(items: list[dict]) -> list[dict]:
    """API times are ISO-8601 with timezone (spec #7); DB stores epoch ms."""
    for it in items:
        it["ts"] = ts_to_iso(it["ts"])
    return items


def _session_iso(items: list[dict]) -> list[dict]:
    """API times are ISO-8601 with timezone (spec #7); DB stores epoch ms.

    A live (in-progress) row stores ts_end=0; it renders as null so the preview
    can show a wall span against "now" instead of the epoch.
    """
    for it in items:
        it["ts_start"] = ts_to_iso(it["ts_start"])
        if it.get("live") and it["ts_end"] == 0:
            it["ts_end"] = None
        else:
            it["ts_end"] = ts_to_iso(it["ts_end"])
    return items


def _state(request: Request) -> Any:
    """Resolve the app state once, so handlers don't traverse the
    request -> app -> state message chain at every use."""
    return request.app.state


@health_router.get("/health")
def health(state: Any = Depends(_state)) -> dict:
    db = state.db
    try:
        with db.conn() as conn:
            conn.execute("SELECT 1").fetchone()
        db_ok = "ok"
    except sqlite3.Error:
        db_ok = "error"
    return {
        "status": "ok",
        "version": __version__,
        "db": db_ok,
        "uptime_s": round(time.time() - state.started),
    }


@search_router.get("/search")
def search(
    state: Any = Depends(_state),
    q: str | None = Query(None, max_length=500),
    kind: Literal["frame", "session"] | None = Query(None),
    window_class: str | None = None,
    player: str | None = None,
    workspace: int | None = Query(None, ge=0),
    monitor: int | None = Query(None, ge=0),
    fullscreen: bool | None = None,
    source: Literal["a11y", "ocr", "transcript"] | None = None,
    sort: Literal["score", "ts"] = Query("ts"),
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    offset: int = Query(0, ge=0),
) -> dict:
    """Merged search over frames (a11y/OCR/title) and watch sessions
    (media title/source), with `kind: frame|session` on every item (#37).

    `q` is optional (#56): without it the surfaces are browsed as a plain
    filtered scan, newest-first (`sort=ts`, the default). With a query, bm25
    is scored per surface; `sort=score` merges both surfaces by score.

    Frame-only filters (workspace/monitor/fullscreen/source=a11y|ocr) are
    ignored by the session surface; `source=transcript` is the session-side
    gate and a no-op for frames. Invalid FTS5 syntax is a 422.
    """
    limit, offset = _paginate(limit, offset)
    q = q.strip() if q else None
    start_ms = _parse_time(start, "start")
    end_ms = _parse_time(end, "end")
    try:
        if kind == "session":
            total, items = state.db.search_watch_sessions(
                q, player=player, source=source, start=start_ms, end=end_ms,
                limit=limit, offset=offset, order=sort)
            items = _session_iso(items)
        elif kind == "frame":
            total, items = state.db.search(
                q, window_class=window_class, workspace=workspace,
                monitor=monitor, fullscreen=fullscreen, source=source,
                start=start_ms, end=end_ms, limit=limit, offset=offset,
                order=sort)
            items = _iso(items)
        else:
            total, items = _merge_search(state, q, window_class, player,
                                         workspace, monitor, fullscreen,
                                         source, start_ms, end_ms,
                                         limit, offset, sort)
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=422, detail=f"invalid search query: {exc}")
    for it in items:
        it["kind"] = "session" if "ts_start" in it else "frame"
    return {"total": total, "items": items}


def _merge_search(state: Any, q: str | None, window_class: str | None,
                  player: str | None, workspace: int | None,
                  monitor: int | None, fullscreen: bool | None,
                  source: str | None, start_ms: int | None, end_ms: int | None,
                  limit: int, offset: int, sort: str) -> tuple[int, list[dict]]:
    """Both surfaces in one timeline, tagged by kind (#37).

    Each surface is fetched with `offset + limit` rows already sorted, then
    merged and re-sliced so pagination stays correct across kinds.
    `sort="score"` interleaves by bm25 score (ties broken newest-first);
    `sort="ts"` is the newest-first merge. In browse mode (no `q`) scores are
    all 0, so score sort degrades to newest-first too.
    """
    order = "ts" if sort == "ts" else "score"
    frame_total, frames = state.db.search(
        q, window_class=window_class, workspace=workspace, monitor=monitor,
        fullscreen=fullscreen, source=source, start=start_ms, end=end_ms,
        limit=limit + offset, offset=0, order=order)
    sess_total, sessions = state.db.search_watch_sessions(
        q, player=player, source=source, start=start_ms, end=end_ms,
        limit=limit + offset, offset=0, order=order)
    if sort == "score":
        pairs = [(-f["score"], -f["ts"], f) for f in frames]
        pairs += [(-s["score"], -s["ts_start"], s) for s in sessions]
    else:
        pairs = [(-f["ts"], 0, f) for f in frames]
        pairs += [(-s["ts_start"], 0, s) for s in sessions]
    pairs.sort()
    items = [it for _, _, it in pairs[offset:offset + limit]]
    _iso([it for it in items if "ts_start" not in it])
    _session_iso([it for it in items if "ts_start" in it])
    return frame_total + sess_total, items


@frames_router.get("/frames")
def list_frames(
    state: Any = Depends(_state),
    window_class: str | None = None,
    trigger: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    offset: int = Query(0, ge=0),
    order: str = Query("asc", pattern="^(asc|desc)$"),
) -> dict:
    limit, offset = _paginate(limit, offset)
    start_ms = _parse_time(start, "start")
    end_ms = _parse_time(end, "end")
    total, items = state.db.list_frames(
        window_class=window_class, trigger=trigger, start=start_ms, end=end_ms,
        limit=limit, offset=offset, desc=(order == "desc"),
    )
    return {"total": total, "items": _iso(items)}


@frames_router.get("/frames/{frame_id}")
def frame_detail(frame_id: int, state: Any = Depends(_state)) -> dict:
    frame = state.db.get_frame(frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail=f"frame {frame_id} not found")
    frame["ts"] = ts_to_iso(frame["ts"])
    return frame


@frames_router.get("/frames/{frame_id}/image")
def frame_image(frame_id: int, state: Any = Depends(_state)):
    frame = state.db.get_frame(frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail=f"frame {frame_id} not found")
    image = state.config.data_path / frame["image_path"]
    if not image.exists():
        raise HTTPException(status_code=404, detail="image file is missing")
    return FileResponse(image, media_type="image/jpeg")


@capture_router.post("/capture")
def manual_capture(state: Any = Depends(_state)) -> dict:
    """Trigger one capture of the active window now (`heimdall capture`).

    Writes a fresh request to `capture.request`, which the capture daemon
    polls; waits for its ack on `capture.ack`, then for the extracted text
    (a11y or OCR, populated asynchronously). Errors: no daemon -> 503, capture
    failure -> 500, the request times out after ~30s.
    """
    config: Config = state.config
    rid = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    try:
        (config.data_path / "capture.request").write_text(
            json.dumps({"id": rid, "ts": now_ms}))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"cannot write capture request: {exc}")

    ack_path = config.data_path / "capture.ack"
    frame_id: int | None = None
    deadline = time.time() + 30.0
    while time.time() < deadline:
        try:
            ack = json.loads(ack_path.read_text())
        except (FileNotFoundError, ValueError):
            ack = None
        if ack and ack.get("id") == rid:
            if ack.get("status") == "error":
                raise HTTPException(status_code=500,
                                    detail=ack.get("detail") or "capture failed")
            frame_id = ack.get("frame_id")
            break
        time.sleep(0.2)
    if frame_id is None:
        raise HTTPException(
            status_code=503,
            detail="capture daemon not responding (is scripts/start-capture.sh running?)",
        )

    frame = state.db.get_frame(frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail=f"frame {frame_id} not found")
    deadline = time.time() + 10.0
    while not (frame.get("a11y_text") or frame.get("ocr_text")) and time.time() < deadline:
        time.sleep(0.3)
        frame = state.db.get_frame(frame_id)
        if frame is None:
            break
    return _iso([frame])[0]


@pipes_router.get("/pipes")
def list_pipes() -> dict:
    return {"names": registered_pipes()}


@pipes_router.post("/pipes/run/{name}")
def run_pipe_endpoint(name: str, state: Any = Depends(_state), day: str | None = None) -> dict:
    resolved_day = today_str() if day is None else day
    try:
        result = run_pipe(
            name,
            day=resolved_day,
            config=state.config,
            db_path=state.db_path,
            llm=state.llm,
        )
    except UnknownPipeError:
        raise HTTPException(status_code=404, detail=f"unknown pipe {name!r}")
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    state.last_runs[name] = result["ts"]
    return result


@status_router.get("/status")
def status(state: Any = Depends(_state)) -> dict:
    config: Config = state.config
    start_ms, end_ms = day_bounds(today_str())
    today = state.db.count_frames(start_ms, end_ms)

    alive, last_event_ms = _capture_status(config, int(time.time() * 1000))

    llama_reachable = _llama_reachable(config.llama_server.base_url, state.transport)
    gate = trace_gate(config.observability.enabled)

    players_fn = getattr(state, "list_players", None) or _list_media_players
    ocr_also = sorted(config.capture.window_class_merge)

    total, items = state.db.list_watch_sessions(limit=1)
    last_session = None
    if items:
        s = items[0]
        last_session = {
            "session_id": s["id"],
            "player": s["player"],
            "media_title": s["media_title"],
            "media_source": s["media_source"],
            "ts_start": s["ts_start"],
            "ts_end": s["ts_end"],
            "transcript_source": s.get("transcript_source"),
        }

    return {
        "server": {
            "status": "ok",
            "version": __version__,
            "uptime_s": round(time.time() - state.started),
        },
        "db": {"frames_today": today, "size_bytes": state.db.size_bytes()},
        "capture": {
            "alive": alive,
            "last_event_ts": ts_to_iso(last_event_ms) if last_event_ms else None,
            "extraction": config.capture.extraction,
            "ocr_also": ocr_also,
            "players": players_fn(),
        },
        "media": {"last_session": last_session},
        "asr": state.asr.pending(),
        "llama": {"reachable": llama_reachable},
        "tracing": {"enabled": gate.enabled, "reason": gate.reason},
        "pipes": {"last_runs": {name: state.last_runs.get(name) for name in registered_pipes()}},
    }


class MediaLiveIn(BaseModel):
    title: str
    href: str
    current_time_us: int | None = None


@sessions_router.post("/media/live")
def media_live(payload: MediaLiveIn, state: Any = Depends(_state)) -> dict:
    """Ingest one tab's streamed reading from the native-messaging host (#44).

    The extension host POSTs the active page's title/URL/video time here; the
    row lands in ``media_stream`` where the daemon's extension resolver reads
    it. Fail-soft by design — a bad payload is a 422, never a daemon crash.
    """
    state.db.upsert_media_stream(
        href=payload.href,
        tab_title=payload.title,
        current_time_us=payload.current_time_us,
        ts=int(time.time() * 1000),
    )
    return {"ok": True}


@sessions_router.get("/sessions")
def list_sessions(
    state: Any = Depends(_state),
    player: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    offset: int = Query(0, ge=0),
) -> dict:
    """Watch sessions, newest first (MPRIS tracking, spec #20 / #35)."""
    limit, offset = _paginate(limit, offset)
    start_ms = _parse_time(start, "start")
    end_ms = _parse_time(end, "end")
    total, items = state.db.list_watch_sessions(
        player=player, start=start_ms, end=end_ms, limit=limit, offset=offset,
    )
    return {"total": total, "items": _session_iso(items)}


@sessions_router.get("/sessions/{session_id}")
def session_detail(session_id: int, state: Any = Depends(_state)) -> dict:
    session = state.db.get_watch_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    return _session_iso([session])[0]


@sessions_router.get("/sessions/{session_id}/transcript")
def session_transcript(session_id: int, state: Any = Depends(_state)):
    """Lazy ASR transcript for a subtitle-less local session (#40).

    Returns the stored transcript (200) when one exists — captions or a prior
    ASR run — otherwise triggers an async ffmpeg + faster-whisper job and
    returns 202 with its status. Poll this same endpoint until it returns 200;
    completed results are cached on the session, so a repeat call never re-runs.
    """
    code, body = state.asr.request(session_id)
    if code == 200:
        return body
    return JSONResponse(status_code=code, content=body)


def _capture_status(config: Config, now_ms: int) -> tuple[bool, int | None]:
    """Capture daemon aliveness from the heartbeat file.

    Alive while the last heartbeat is within 3x the keepalive interval.
    """
    heartbeat = config.data_path / "capture.heartbeat"
    if not heartbeat.exists():
        return False, None
    try:
        last_event_ms = int(heartbeat.read_text().strip())
    except ValueError:
        return False, None
    grace = config.capture.keepalive_min * 60_000 * 3
    return (now_ms - last_event_ms) < grace, last_event_ms


def _list_media_players() -> list[dict]:
    """MPRIS players currently up via playerctl, with playback status.

    Best-effort: missing playerctl or a hung bus degrades to an empty list so
    the down-detector never stalls. `create_app(list_players=...)` overrides
    this seam in tests.
    """
    try:
        r = subprocess.run(["playerctl", "-l"], capture_output=True,
                           text=True, timeout=3)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    names = [line.strip() for line in r.stdout.splitlines() if line.strip()]
    players: list[dict] = []
    for name in names:
        status = "unknown"
        try:
            s = subprocess.run(["playerctl", "status", "-p", name],
                               capture_output=True, text=True, timeout=3)
            if s.returncode == 0:
                status = s.stdout.strip().lower() or status
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        players.append({"name": name, "status": status})
    players.sort(key=lambda p: (p["status"] != "playing", p["name"]))
    return players


def _llama_reachable(base_url: str, transport: httpx.AsyncBaseTransport | None) -> bool:
    try:
        with httpx.Client(base_url=base_url, timeout=2.0, transport=transport or httpx.HTTPTransport()) as c:
            r = c.get("/health")
            return r.status_code == 200
    except Exception:
        return False
