"""Streamlit dashboard prototype for heimdall. THROWAWAY.

Reads the live heimdall API (serve on 127.0.0.1:3931) and renders a
searchable, live-refreshing view of everything the daemon collects:
watch sessions (with transcripts + cues), OCR frames, the extension media
stream, and system status. Run:

    .venv/bin/streamlit run prototype_streamlit.py --server.port 8501

This is a design probe — pick a winner (or steal bits), then delete.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

API = "http://127.0.0.1:3931"


def api(path: str, **params) -> dict:
    r = requests.get(API + path, params=params or None, timeout=10)
    r.raise_for_status()
    return r.json()


def image_bytes(frame_id: int) -> bytes:
    r = requests.get(f"{API}/frames/{frame_id}/image", timeout=10)
    r.raise_for_status()
    return r.content


def wall(a: str, b: str | None = None) -> str:
    end = datetime.now(timezone.utc) if b is None else datetime.fromisoformat(b.replace("Z", "+00:00"))
    start = datetime.fromisoformat(a.replace("Z", "+00:00"))
    s = max(0, int((end - start).total_seconds()))
    return f"{s // 3600}h{(s % 3600) // 60}m{s % 60:02d}s"


def video(us) -> str:
    us = int(us or 0)
    s = max(0, us // 1_000_000)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def sane_len(us) -> int:
    us = int(us or 0)
    return us if 0 < us < 9e15 else 0


def parse_cues(it) -> list[dict]:
    try:
        c = json.loads(it.get("cues_json") or "[]")
        return c if isinstance(c, list) else []
    except Exception:
        return []


def parse_ranges(it) -> list[tuple[int, int]]:
    raw = it.get("ranges")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    try:
        return [(int(a), int(b)) for a, b in (raw or []) if int(b) > int(a)]
    except Exception:
        return []


def merge_ranges(rs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sort + merge overlapping/adjacent video-time ranges (µs)."""
    out: list[tuple[int, int]] = []
    for a, b in sorted(rs):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def total_watched_us(it) -> int:
    """Actually-watched video time in µs, from the ranges column (pos_end is
    unreliable: 0 for closed sessions)."""
    return sum(b - a for a, b in parse_ranges(it))


st.set_page_config(page_title="heimdall", page_icon="👁", layout="wide")

st.markdown("""
<style>
  .segtrack { position: relative; height: 22px; border-radius: 4px;
              background: #2b2b2b; overflow: hidden; margin: 6px 0; }
  .segcell { position: absolute; top: 0; bottom: 0;
             background: #4f8df9; border-radius: 2px; }
</style>
""", unsafe_allow_html=True)

st.title("heimdall")
st.caption("watch-sessions · transcripts · OCR frames · extension stream")

# --- load data ---
try:
    sessions = api("/sessions", limit=100)
    status = api("/status")
    frames = api("/frames", limit=50, order="desc")
    stream = api("/prototype/stream")
except Exception as exc:  # noqa: BLE001
    st.error(f"can't reach heimdall API at {API}: {exc}")
    st.stop()

cap = status.get("capture") or {}
db = status.get("db") or {}
server = status.get("server") or {}
sess_items = sessions.get("items", [])
frame_items = frames.get("items", [])

# --- sidebar status ---
with st.sidebar:
    c1, c2 = st.columns(2)
    c1.metric("capture", "ALIVE" if cap.get("alive") else "DEAD",
              delta=None, delta_color="off")
    c2.metric("frames today", db.get("frames_today", 0))
    st.metric("db size", f"{round((db.get('size_bytes') or 0) / 1024)} KB")
    st.metric("server up", f"{round((server.get('uptime_s') or 0) / 60)}m")
    if stream.get("items"):
        st.subheader("live stream")
        for s in stream["items"][:4]:
            st.caption(f"{s.get('tab_title', '—')}\n{video(s.get('current_time_us'))}")

tab_videos, tab_sessions, tab_transcripts, tab_frames, tab_search = st.tabs(
    ["Videos", "Sessions", "Transcripts", "OCR frames", "Search"])


def segment_strip(merged: list[tuple[int, int]], length_us: int) -> str:
    """HTML timeline showing which segments of a video were watched."""
    if not length_us or not merged:
        return "<div class='seg' style='color:#888'>no watched segments</div>"
    cells = []
    for a, b in merged:
        left = a / length_us * 100
        width = max(0.4, (b - a) / length_us * 100)
        cells.append(
            f"<div class='segcell' style='left:{left:.1f}%;width:{width:.1f}%' "
            f"title='{video(a)} → {video(b)}'></div>")
    return "<div class='segtrack'>" + "".join(cells) + "</div>"


# ---------------- Videos (per-link aggregation) ----------------
with tab_videos:
    st.subheader("Watched per video")
    by_video: dict[str, dict] = {}
    for it in sess_items:
        key = it.get("media_source") or it.get("media_id")
        if not key:
            continue
        v = by_video.setdefault(key, {
            "media_source": it.get("media_source"),
            "media_id": it.get("media_id"),
            "title": it.get("media_title") or "(untitled)",
            "length": sane_len(it.get("length")),
            "sessions": 0,
            "live": False,
            "first": it["ts_start"],
            "last": it.get("ts_end"),
            "ranges": [],
        })
        v["sessions"] += 1
        v["live"] = v["live"] or bool(it.get("live"))
        v["ranges"].extend(parse_ranges(it))
        v["last"] = it.get("ts_end") or v["last"]
    if not by_video:
        st.info("no sessions with a media link yet.")
    for key, v in sorted(by_video.items(), key=lambda kv: kv[1]["last"] or "", reverse=True):
        merged = merge_ranges(v["ranges"])
        watched = sum(b - a for a, b in merged)
        len_us = v["length"]
        pct = min(100, round(watched / len_us * 100)) if len_us else 0
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
            c1.markdown(f"**{v['title']}**  `{v['media_id'] or ''}`"
                        + ("  `● watching`" if v["live"] else ""))
            c2.caption("sessions")
            c2.write(v["sessions"])
            c3.caption("watched")
            c3.write(video(watched))
            c4.caption("of length")
            c4.write(video(len_us) if len_us else "—")
            st.markdown(segment_strip(merged, len_us), unsafe_allow_html=True)
            st.caption(f"first: {v['first']}  ·  last: {v['last'] or 'now'}  ·  "
                       f"segments: {len(merged)}  ·  {pct}% watched")
            with st.expander("watched segments"):
                for a, b in merged:
                    st.caption(f"{video(a)} → {video(b)}  ({video(b - a)})")

# ---------------- Sessions ----------------
with tab_sessions:
    st.subheader(f"Watch sessions ({len(sess_items)})")
    st.caption("each row is one capture poll span; the same video spawns many rows. "
               "real = wall-clock span, watched = video-time actually played (from ranges).")
    for it in sess_items:
        live = bool(it.get("live"))
        title = it.get("media_title") or "(untitled)"
        badge = "● LIVE" if live else "ended"
        watched = total_watched_us(it)
        len_us = sane_len(it.get("length"))
        pct = min(100, round(watched / len_us * 100)) if len_us else 0
        with st.container(border=True):
            cols = st.columns([3, 1, 1, 1, 1])
            cols[0].markdown(f"**{title}**  `{badge}`")
            cols[1].caption("player")
            cols[1].write(it.get("player"))
            cols[2].caption("real")
            cols[2].write(wall(it["ts_start"], it.get("ts_end")))
            cols[3].caption("watched")
            cols[3].write(video(watched))
            cols[4].caption("video-time")
            cols[4].write(video(it.get("pos_start")) + " → " + video(it.get("pos_end")))
            if it.get("media_id"):
                st.caption(f"{it['media_id']} — {it.get('media_source')}")
            st.caption(f"real span: {it['ts_start']} → {it.get('ts_end') or 'now'}")
            if len_us:
                st.progress(pct / 100, text=f"{pct}% of video watched")

# ---------------- Transcripts ----------------
with tab_transcripts:
    st.subheader("Transcripts")
    with_tran = [it for it in sess_items if it.get("transcript")]
    if not with_tran:
        st.info("no transcripts yet — watch a YouTube video and let the session close.")
    for it in with_tran:
        title = it.get("media_title") or "(untitled)"
        with st.expander(f"{title} — {it.get('media_id', 'no id')}  ·  {wall(it['ts_start'], it.get('ts_end'))}"):
            st.write(it["transcript"])
            cues = parse_cues(it)
            if cues:
                st.markdown("**cues**")
                df = pd.DataFrame([
                    {"start_ms": c.get("start_ms"), "end_ms": c.get("end_ms"),
                     "text": c.get("text")} for c in cues])
                st.dataframe(df, use_container_width=True, hide_index=True)

# ---------------- OCR frames ----------------
with tab_frames:
    st.subheader(f"OCR frames ({frames.get('total', len(frame_items))})")
    if not frame_items:
        st.info("no frames yet.")
    for f in frame_items:
        with st.container(border=True):
            cols = st.columns([1, 3])
            try:
                cols[0].image(image_bytes(f["id"]), width=260)
            except Exception:  # noqa: BLE001
                cols[0].caption("(no image)")
            with cols[1]:
                st.markdown(f"**{f.get('window_title') or '(untitled)'}**  `{f.get('window_class') or ''}`")
                st.caption(
                    f"{f['ts']} · ocr: {f.get('ocr_engine') or '—'} "
                    f"({round(f.get('ocr_sec') or 0, 2)}s) · trigger: {f.get('trigger')} · "
                    f"monitor: {f.get('monitor')} · ws: {f.get('workspace')}")
                if f.get("ocr_text"):
                    st.write(f["ocr_text"])
                if f.get("a11y_text"):
                    with st.expander("a11y text"):
                        st.write(f["a11y_text"])

# ---------------- Search ----------------
with tab_search:
    q = st.text_input("search frames + sessions", placeholder="e.g. create, enigma…")
    kind = st.selectbox("kind", ["both", "frame", "session"])
    if q:
        params = {"q": q, "limit": 50}
        if kind != "both":
            params["kind"] = kind
        try:
            res = requests.get(f"{API}/search", params=params, timeout=10).json()
        except Exception as exc:  # noqa: BLE001
            st.error(f"search failed: {exc}")
            res = {"total": 0, "items": []}
        st.write(f"{res.get('total', 0)} hits")
        for hit in res.get("items", []):
            kind_badge = f"`{hit.get('kind')}`" if hit.get("kind") else ""
            st.markdown(f"- {kind_badge} **{hit.get('ts')}** {hit.get('window_class') or hit.get('media_title') or ''} — {hit.get('snippet') or hit.get('window_title') or ''}")
