"""HTTP routers: health, search, frames, pipes, status.

All responses are JSON with snake_case fields; errors use FastAPI's
{"detail": ...} convention. Loopback-only bind is the security boundary.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

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
    for it in items:
        it["ts_start"] = ts_to_iso(it["ts_start"])
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
    q: str = Query(..., min_length=1),
    window_class: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    offset: int = Query(0, ge=0),
) -> dict:
    limit, offset = _paginate(limit, offset)
    start_ms = _parse_time(start, "start")
    end_ms = _parse_time(end, "end")
    try:
        total, items = state.db.search(
            q, window_class=window_class, start=start_ms, end=end_ms,
            limit=limit, offset=offset,
        )
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=422, detail=f"invalid search query: {exc}")
    return {"total": total, "items": _iso(items)}


@frames_router.get("/frames")
def list_frames(
    state: Any = Depends(_state),
    window_class: str | None = None,
    trigger: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    offset: int = Query(0, ge=0),
) -> dict:
    limit, offset = _paginate(limit, offset)
    start_ms = _parse_time(start, "start")
    end_ms = _parse_time(end, "end")
    total, items = state.db.list_frames(
        window_class=window_class, trigger=trigger, start=start_ms, end=end_ms,
        limit=limit, offset=offset,
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

    return {
        "server": {
            "status": "ok",
            "version": __version__,
            "uptime_s": round(time.time() - state.started),
        },
        "db": {"frames_today": today, "size_bytes": state.db.size_bytes()},
        "capture": {"alive": alive, "last_event_ts": ts_to_iso(last_event_ms) if last_event_ms else None},
        "llama": {"reachable": llama_reachable},
        "tracing": {"enabled": gate.enabled, "reason": gate.reason},
        "pipes": {"last_runs": {name: state.last_runs.get(name) for name in registered_pipes()}},
    }


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


@sessions_router.get("/", response_class=HTMLResponse)
def sessions_preview(state: Any = Depends(_state)) -> HTMLResponse:
    """Minimal read-only preview of watch sessions (user request, 2026-08-03).

    Loopback-only like the rest of the API; the page just renders GET /sessions
    live with a client-side auto-refresh. `transcript` renders when the #41
    merged search starts supplying it — GET /sessions stays the data contract.
    """
    return HTMLResponse(PREVIEW_HTML)


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


PREVIEW_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>heimdall — watch sessions</title>
<style>
  body { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 2rem; background: #111; color: #ddd; }
  h1 { font-size: 1.1rem; color: #8af; }
  table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
  th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #2a2a2a; vertical-align: top; }
  th { color: #888; font-weight: 600; position: sticky; top: 0; background: #111; }
  .player { color: #9f9; }
  .src { color: #f90; word-break: break-all; }
  .ranges { color: #cc8; }
  .span { color: #8af; white-space: nowrap; }
  .transcript { color: #aaa; max-width: 40rem; }
  #meta { color: #888; margin: 0.4rem 0 1rem; }
</style>
</head>
<body>
<h1>heimdall — watch sessions</h1>
<div id="meta">loading…</div>
<table>
<thead><tr>
  <th>when</th><th>player</th><th>title</th><th>source</th>
  <th>watched</th><th>wall</th><th>transcript</th>
</tr></thead>
<tbody id="rows"></tbody>
</table>
<script>
const $rows = document.getElementById("rows");
const $meta = document.getElementById("meta");

function fmtVideo(us) {
  let s = Math.max(0, Math.floor((us || 0) / 1e6));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? h + ":" + String(m).padStart(2, "0") + ":" + String(sec).padStart(2, "0")
           : m + ":" + String(sec).padStart(2, "0");
}
function fmtWall(a, b) {
  const ms = Math.max(0, new Date(b) - new Date(a));
  const s = Math.floor(ms / 1000), m = Math.floor(s / 60), h = Math.floor(m / 60);
  return (h ? h + "h" : "") + (m % 60) + "m" + String(s % 60).padStart(2, "0") + "s";
}
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
async function refresh() {
  try {
    const r = await fetch("/sessions?limit=50");
    const body = await r.json();
    $meta.textContent = body.total + " watch session(s) — auto-refresh 5s";
    const rows = body.items.map(it => {
      const ranges = (it.ranges || []).map(r => fmtVideo(r[0]) + "–" + fmtVideo(r[1])).join(", ") || "—";
      const src = it.media_source ? '<span class="src">' + esc(it.media_source) + "</span>" : "—";
      return "<tr><td>" + esc(it.ts_start) + "</td>"
        + '<td class="player">' + esc(it.player) + "</td>"
        + "<td>" + esc(it.media_title) + "</td>"
        + "<td>" + src + "</td>"
        + '<td class="ranges">' + esc(ranges) + "</td>"
        + '<td class="span">' + fmtWall(it.ts_start, it.ts_end) + "</td>"
        + '<td class="transcript">' + (it.transcript ? esc(it.transcript) : "") + "</td></tr>";
    }).join("");
    $rows.innerHTML = rows || '<tr><td colspan="7">no sessions yet</td></tr>';
  } catch (e) { /* keep the last table on transient errors */ }
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


def _llama_reachable(base_url: str, transport: httpx.AsyncBaseTransport | None) -> bool:
    try:
        with httpx.Client(base_url=base_url, timeout=2.0, transport=transport or httpx.HTTPTransport()) as c:
            r = c.get("/health")
            return r.status_code == 200
    except Exception:
        return False
