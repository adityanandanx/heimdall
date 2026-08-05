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
sessions_router = APIRouter()
capture_router = APIRouter()

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
    q: str = Query(..., min_length=1),
    kind: Literal["frame", "session"] | None = Query(None),
    window_class: str | None = None,
    player: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    offset: int = Query(0, ge=0),
) -> dict:
    """Merged full-text search over frames (a11y/OCR/title) and watch sessions
    (media title/source), with `kind: frame|session` on every item (#37).

    `kind=frame` and `kind=session` filter to one surface; the default mixes
    both into a single newest-first timeline. bm25 is scored per surface.
    Invalid FTS5 syntax is a 422, matching the single-surface behavior.
    """
    limit, offset = _paginate(limit, offset)
    start_ms = _parse_time(start, "start")
    end_ms = _parse_time(end, "end")
    try:
        if kind == "session":
            total, items = state.db.search_watch_sessions(
                q, player=player, start=start_ms, end=end_ms,
                limit=limit, offset=offset)
            items = _session_iso(items)
        elif kind == "frame":
            total, items = state.db.search(
                q, window_class=window_class, start=start_ms, end=end_ms,
                limit=limit, offset=offset)
            items = _iso(items)
        else:
            total, items = _merge_search(state, q, window_class, player,
                                         start_ms, end_ms, limit, offset)
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=422, detail=f"invalid search query: {exc}")
    for it in items:
        it["kind"] = "session" if "ts_start" in it else "frame"
    return {"total": total, "items": items}


def _merge_search(state: Any, q: str, window_class: str | None, player: str | None,
                  start_ms: int | None, end_ms: int | None,
                  limit: int, offset: int) -> tuple[int, list[dict]]:
    """Both surfaces, newest-first, tagged by kind (#37).

    Each surface is fetched with `offset + limit` rows already sorted newest-
    first, then merged and re-sliced so pagination stays correct across kinds.
    """
    frame_total, frames = state.db.search(
        q, window_class=window_class, start=start_ms, end=end_ms,
        limit=limit + offset, offset=0, order="ts")
    sess_total, sessions = state.db.search_watch_sessions(
        q, player=player, start=start_ms, end=end_ms,
        limit=limit + offset, offset=0, order="ts")
    pairs = [(f["ts"], f) for f in frames] + [(s["ts_start"], s) for s in sessions]
    pairs.sort(key=lambda p: p[0], reverse=True)
    items = [it for _, it in pairs[offset:offset + limit]]
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
  .badge { color: #0c0; font-size: 0.75rem; }
  .badge.paused { color: #f90; }
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
  const end = b == null ? new Date() : new Date(b);   // live rows run to "now"
  const ms = Math.max(0, end - new Date(a));
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
    const live = body.items.filter(it => it.live).length;
    $meta.textContent = body.total + " watch session(s) — " + live + " live · "
      + (body.total - live) + " finished — auto-refresh 5s";
    const rows = body.items.map(it => {
      const ranges = (it.ranges || []).map(r => fmtVideo(r[0]) + "–" + fmtVideo(r[1])).join(", ") || "—";
      const src = it.media_source ? '<span class="src">' + esc(it.media_source) + "</span>" : "—";
      const badge = it.live
        ? (it.paused
            ? '<span class="badge paused">● paused</span> '
            : '<span class="badge">● watching</span> ')
        : "";
      const title = badge + esc(it.media_title);
      return "<tr><td>" + esc(it.ts_start) + "</td>"
        + '<td class="player">' + esc(it.player) + "</td>"
        + "<td>" + title + "</td>"
        + "<td>" + src + "</td>"
        + '<td class="ranges">' + esc(ranges) + "</td>"
        + '<td class="span">' + fmtWall(it.ts_start, it.ts_end) + "</td>"
        + '<td class="transcript">' + (it.transcript && !it.live ? esc(it.transcript) : "") + "</td></tr>";
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
