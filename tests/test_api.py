"""HTTP API tests (primary seam): shapes, filters, pagination, pipe run contract."""

from __future__ import annotations

import time
from datetime import datetime

from fastapi.testclient import TestClient

from heimdall.api.app import create_app
from heimdall.config import Config
from heimdall.timeutil import day_bounds, ts_to_iso

from conftest import FIXTURE_DAY, BREAKDOWN_COMPLETION, RECAP_COMPLETION, build_day_db, mock_llm_response


# ---- /health ----

def test_health(api_client: TestClient):
    r = api_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["db"] == "ok"
    assert body["uptime_s"] >= 0


# ---- / (day browser UI) ----

def test_root_serves_day_browser(api_client: TestClient):
    r = api_client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "heimdall · day browser" in r.text
    assert "loadDay" in r.text
    # same-origin API: no hardcoded host, no embedded snapshot
    assert "127.0.0.1" not in r.text
    assert "embedded data snapshot" not in r.text


# ---- /search ----

def test_search_shape(api_client: TestClient):
    r = api_client.get("/search", params={"q": "youtube"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"total", "items"}
    item = body["items"][0]
    assert set(item) == {"id", "ts", "window_class", "window_title", "workspace",
                         "image_path", "snippet", "score", "kind"}
    assert item["image_path"].startswith("frames/")
    assert item["kind"] == "frame"
    assert body["total"] == 1


def test_search_ts_is_iso8601_with_tz(api_client: TestClient):
    r = api_client.get("/search", params={"q": "youtube"})
    ts = r.json()["items"][0]["ts"]
    dt = datetime.fromisoformat(ts)
    assert dt.tzinfo is not None
    assert ts.endswith(("Z", "+05:30", "+05:00"))  # a concrete offset, not naive
    r = api_client.get("/frames")
    for it in r.json()["items"]:
        assert datetime.fromisoformat(it["ts"]).tzinfo is not None


def test_search_requires_q(api_client: TestClient):
    """#56: q became optional — no query browses everything, newest-first."""
    r = api_client.get("/search")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 8
    assert [it["kind"] for it in body["items"]] == ["frame"] * 8
    ts = [datetime.fromisoformat(it["ts"]) for it in body["items"]]
    assert ts == sorted(ts, reverse=True)


def test_search_invalid_query(api_client: TestClient):
    r = api_client.get("/search", params={"q": "youtube AND ("})
    assert r.status_code == 422


def test_search_filters(api_client: TestClient):
    start_ms, end_ms = day_bounds(FIXTURE_DAY)
    r = api_client.get("/search", params={
        "q": "docs OR terminal OR leetcode",
        "window_class": "firefox",
        "start": f"{start_ms / 1000:.0f}",  # not valid ISO; use real ISO instead
    })
    assert r.status_code == 422  # epoch is not ISO-8601 with tz
    r = api_client.get("/search", params={
        "q": "docs OR terminal OR leetcode",
        "window_class": "firefox",
    })
    body = r.json()
    assert {it["window_class"] for it in body["items"]} == {"firefox"}


def test_search_time_range_and_pagination(api_client: TestClient):
    start_ms, _ = day_bounds(FIXTURE_DAY)
    start_iso = ts_to_iso(start_ms + 30 * 60_000)
    end_iso = ts_to_iso(start_ms + 120 * 60_000)
    r = api_client.get("/search", params={
        "q": "docs OR terminal OR leetcode OR langgraph",
        "start": start_iso,
        "end": end_iso,
    })
    body = r.json()
    assert body["total"] >= 2
    r2 = api_client.get("/search", params={"q": "docs OR terminal OR leetcode OR langgraph",
                                           "limit": 1, "offset": 1})
    assert len(r2.json()["items"]) == 1
    r3 = api_client.get("/search", params={"q": "docs OR terminal", "limit": 101})
    assert r3.status_code == 200  # limit clamped to max 100
    r4 = api_client.get("/search", params={"q": "docs OR terminal", "limit": 0})
    assert r4.status_code == 422


def test_search_kind_frame_filter(api_client: TestClient, db):
    """kind=frame keeps only frame hits; sessions are excluded (#37)."""
    _insert_session(db, title="Inception (2010)", wall_ms=1_000)
    body = api_client.get("/search", params={"q": "inception", "kind": "frame"}).json()
    assert body["total"] == 1
    assert body["items"][0]["window_title"] == "Inception (2010)"
    assert all(it["kind"] == "frame" for it in body["items"])


def test_search_kind_session_filter(api_client: TestClient, db):
    """kind=session keeps only session hits; frames are excluded (#37)."""
    _insert_session(db, title="Inception (2010)", wall_ms=1_000)
    body = api_client.get("/search", params={"q": "inception", "kind": "session"}).json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["kind"] == "session"
    for key in ("id", "player", "media_title", "media_source", "ts_start", "ts_end",
                "snippet", "score", "live"):
        assert key in item
    assert item["media_title"] == "Inception (2010)"
    assert datetime.fromisoformat(item["ts_start"]).tzinfo is not None


def test_search_session_live_renders_null_ts_end(api_client: TestClient, db):
    """A live session surfaced by search keeps ts_end null and live: 1 (#37)."""
    db.insert_live_session(
        "vlc", "Inception (2010)", "file:///mnt/movies/Inception.mkv", None,
        ts_start=1_000, pos_start=600_000_000, length=7_200_000_000,
        ranges=[[600_000_000, 630_000_000]],
    )
    item = api_client.get("/search", params={"q": "inception", "kind": "session"}).json()["items"][0]
    assert item["live"] == 1
    assert item["ts_end"] is None


def test_search_kind_invalid(api_client: TestClient):
    assert api_client.get("/search", params={"q": "youtube", "kind": "bogus"}).status_code == 422


def test_search_mixed_kinds_newest_first(api_client: TestClient, db):
    """Default /search mixes frames + sessions into one newest-first timeline."""
    start_ms, _ = day_bounds(FIXTURE_DAY)
    _insert_session(db, title="Inception (2010)", wall_ms=start_ms + 55 * 60_000)
    body = api_client.get("/search", params={"q": "inception"}).json()
    assert body["total"] == 2
    kinds = [it["kind"] for it in body["items"]]
    assert kinds == ["session", "frame"]  # session at +55 beats the mpv frame at +50
    assert body["items"][0]["ts_start"] > body["items"][1]["ts"]


def test_search_crosses_frame_text_and_session_title(api_client: TestClient, db):
    """One query matches a frame's a11y/OCR text AND a session's media title."""
    start_ms, _ = day_bounds(FIXTURE_DAY)
    _insert_session(db, title="checkpointers deep dive", wall_ms=start_ms + 10 * 60_000)
    body = api_client.get("/search", params={"q": "checkpointers"}).json()
    assert body["total"] == 2
    kinds = [it["kind"] for it in body["items"]]
    assert kinds == ["frame", "session"]  # frame at +20 is newer than the session at +10
    assert "checkpointers" in body["items"][0]["snippet"]  # a11y-text hit
    assert body["items"][1]["media_title"] == "checkpointers deep dive"


def test_search_time_range_applies_to_sessions(api_client: TestClient, db):
    """start/end filter the session surface too, not just frames (#37)."""
    start_ms, _ = day_bounds(FIXTURE_DAY)
    _insert_session(db, title="Inception (2010)", wall_ms=start_ms + 10 * 60_000)
    body = api_client.get("/search", params={
        "q": "inception",
        "start": ts_to_iso(start_ms + 40 * 60_000),
        "end": ts_to_iso(start_ms + 60 * 60_000),
    }).json()
    assert body["total"] == 1  # only the mpv frame at +50; the session at +10 is cut
    assert body["items"][0]["kind"] == "frame"


def test_search_merged_pagination(api_client: TestClient, db):
    """Paging slices across the merged timeline, keeping totals consistent."""
    start_ms, _ = day_bounds(FIXTURE_DAY)
    _insert_session(db, title="Inception (2010)", wall_ms=start_ms + 55 * 60_000)
    page1 = api_client.get("/search", params={"q": "inception", "limit": 1}).json()
    assert page1["total"] == 2
    assert [it["kind"] for it in page1["items"]] == ["session"]
    page2 = api_client.get("/search", params={"q": "inception", "limit": 1, "offset": 1}).json()
    assert page2["total"] == 2
    assert [it["kind"] for it in page2["items"]] == ["frame"]


# ---- /search: rich filters + browse mode (#56) ----

def test_search_browse_mode_filters(api_client: TestClient):
    """No text + filters = a plain filtered scan (browse mode)."""
    body = api_client.get("/search", params={"window_class": "firefox"}).json()
    assert body["total"] == 3
    assert {it["window_class"] for it in body["items"]} == {"firefox"}


def test_search_browse_mode_merges_kinds(api_client: TestClient, db):
    start_ms, _ = day_bounds(FIXTURE_DAY)
    _insert_session(db, title="Inception (2010)", wall_ms=start_ms + 95 * 60_000)
    body = api_client.get("/search").json()
    assert body["total"] == 9
    assert [it["kind"] for it in body["items"][:3]] == ["session", "frame", "frame"]


def test_search_browse_mode_pagination(api_client: TestClient):
    body = api_client.get("/search", params={"limit": 5, "offset": 3}).json()
    assert body["total"] == 8
    assert len(body["items"]) == 5
    ids = [it["id"] for it in body["items"]]
    assert ids == sorted(ids, reverse=True)  # newest-first, sliced


def test_search_workspace_monitor_fullscreen_filters(api_client: TestClient):
    assert api_client.get("/search", params={"workspace": 2}).json()["total"] == 8
    assert api_client.get("/search", params={"workspace": 9}).json()["total"] == 0
    assert api_client.get("/search", params={"monitor": 0}).json()["total"] == 8
    assert api_client.get("/search", params={"monitor": 1}).json()["total"] == 0
    assert api_client.get("/search", params={"fullscreen": True}).json()["total"] == 0
    assert api_client.get("/search", params={"fullscreen": False}).json()["total"] == 8


def test_search_source_filters(api_client: TestClient):
    """source=a11y|ocr restricts frames to the text column that won."""
    a11y = api_client.get("/search", params={"source": "a11y", "kind": "frame"}).json()
    assert a11y["total"] == 3
    assert all(it["snippet"] for it in a11y["items"])  # snippet falls back to the plain text
    ocr = api_client.get("/search", params={"source": "ocr", "kind": "frame"}).json()
    assert ocr["total"] == 4
    assert all(it["snippet"] for it in ocr["items"])


def test_search_source_transcript_gates_sessions(api_client: TestClient, db):
    """source=transcript keeps only sessions with a transcript attached."""
    start_ms, _ = day_bounds(FIXTURE_DAY)
    sid = _insert_session(db, title="checkpointers deep dive", wall_ms=start_ms + 10 * 60_000)
    before = api_client.get("/search", params={
        "q": "checkpointers", "kind": "session", "source": "transcript",
    }).json()
    assert before["total"] == 0
    db.update_session_transcript(
        sid, cues_json=None,
        transcript="deep dive into checkpointers and memory", transcript_source="asr")
    after = api_client.get("/search", params={
        "q": "checkpointers", "kind": "session", "source": "transcript",
    }).json()
    assert after["total"] == 1
    assert after["items"][0]["id"] == sid
    # a11y/ocr are no-ops for sessions: the session still matches without them
    plain = api_client.get("/search", params={
        "q": "checkpointers", "kind": "session", "source": "a11y",
    }).json()
    assert plain["total"] == 1


def test_search_sort_score_descends(api_client: TestClient, db):
    """sort=score merges both surfaces by bm25 score, descending."""
    start_ms, _ = day_bounds(FIXTURE_DAY)
    _insert_session(db, title="checkpointers deep dive", wall_ms=start_ms + 10 * 60_000)
    body = api_client.get("/search", params={"q": "checkpointers", "sort": "score"}).json()
    assert body["total"] == 2
    scores = [it["score"] for it in body["items"]]
    assert scores == sorted(scores, reverse=True)
    assert {it["kind"] for it in body["items"]} == {"frame", "session"}


def test_search_sort_ts_newest_first(api_client: TestClient, db):
    """sort=ts keeps the newest-first merged timeline, explicitly."""
    start_ms, _ = day_bounds(FIXTURE_DAY)
    _insert_session(db, title="Inception (2010)", wall_ms=start_ms + 55 * 60_000)
    body = api_client.get("/search", params={"q": "inception", "sort": "ts"}).json()
    assert [it["kind"] for it in body["items"]] == ["session", "frame"]


def test_search_sort_invalid(api_client: TestClient):
    assert api_client.get("/search", params={"q": "youtube", "sort": "bogus"}).status_code == 422
    assert api_client.get("/search", params={"q": "youtube", "monitor": -1}).status_code == 422


# ---- /frames ----

def test_frames_list(api_client: TestClient):
    r = api_client.get("/frames")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 8
    assert len(body["items"]) == 8
    ts = [it["ts"] for it in body["items"]]
    assert ts == sorted(ts)
    item = body["items"][0]
    for key in ("id", "ts", "window_class", "window_title", "workspace", "monitor",
                "fullscreen", "trigger", "image_path", "image_bytes", "ocr_text", "ocr_sec",
                "a11y_text", "a11y_json", "ocr_engine"):
        assert key in item


def test_frames_filters_and_pagination(api_client: TestClient):
    r = api_client.get("/frames", params={"window_class": "firefox", "limit": 2, "offset": 1})
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert {it["window_class"] for it in body["items"]} == {"firefox"}
    r = api_client.get("/frames", params={"trigger": "keepalive"})
    assert r.json()["total"] == 2


def test_frames_detail(api_client: TestClient):
    frame_id = api_client.get("/frames").json()["items"][0]["id"]
    r = api_client.get(f"/frames/{frame_id}")
    assert r.status_code == 200
    assert r.json()["id"] == frame_id


def test_frames_detail_404(api_client: TestClient):
    assert api_client.get("/frames/999999").status_code == 404


def test_frame_detail_includes_a11y(api_client: TestClient):
    """Frame detail carries the a11y winner: text + role/name structure."""
    body = api_client.get("/frames").json()
    a11y_id = next(it["id"] for it in body["items"] if it["a11y_text"])
    r = api_client.get(f"/frames/{a11y_id}")
    assert r.status_code == 200
    frame = r.json()
    assert frame["a11y_text"] == "event loop debounce and throttle\nAPScheduler cron daily recap"
    assert "document web" in frame["a11y_json"]
    assert frame["ocr_text"] is None

    # a11y-blind frames keep NULL text in detail too
    ocr_id = next(it["id"] for it in body["items"]
                  if it["window_title"] == "youtube.com/watch?v=dQw4w9WgXcQ")
    ocr_frame = api_client.get(f"/frames/{ocr_id}").json()
    assert ocr_frame["a11y_text"] is None
    assert ocr_frame["a11y_json"] is None
    assert ocr_frame["ocr_text"] == "never gonna give you up rick astley"


def test_search_matches_a11y_text(api_client: TestClient):
    """a11y_won frames are searchable through their flattened tree text."""
    r = api_client.get("/search", params={"q": "debounce"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    for it in body["items"]:
        assert it["window_title"] == "capture.py — heimdall"
        assert it["snippet"] is not None


def test_search_snippet_comes_from_a11y(api_client: TestClient):
    r = api_client.get("/search", params={"q": "debounce"})
    snippet = r.json()["items"][0]["snippet"]
    assert "**debounce**" in snippet
    # and OCR-won hits still snippet from ocr_text
    r2 = api_client.get("/search", params={"q": "rick"})
    assert "**rick**" in r2.json()["items"][0]["snippet"]


def test_frame_image_serves_jpeg(api_client: TestClient):
    frame_id = api_client.get("/frames").json()["items"][0]["id"]
    r = api_client.get(f"/frames/{frame_id}/image")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content.startswith(b"\xff\xd8\xff\xe0")


def test_frame_image_missing_404(data_dir, db):
    cfg = Config(data_dir=data_dir)
    app = create_app(cfg, db_path=db.path, llm_transport=mock_llm_response(RECAP_COMPLETION))
    with TestClient(app) as client:
        frame_id = client.get("/frames").json()["items"][0]["id"]
        import os
        image = data_dir / client.get(f"/frames/{frame_id}").json()["image_path"]
        os.remove(image)
        assert client.get(f"/frames/{frame_id}/image").status_code == 404


# ---- /pipes ----

def test_pipes_list(api_client: TestClient):
    r = api_client.get("/pipes")
    assert r.json() == {"names": ["day-recap", "time-breakdown"]}


def test_run_pipe_contract(api_client: TestClient):
    r = api_client.post("/pipes/run/day-recap")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"pipe", "ts", "run_ms", "output_markdown", "output_path",
                         "trace_url", "frame_count"}
    assert body["pipe"] == "day-recap"
    assert body["frame_count"] == 8
    assert body["output_path"].startswith("output/day-recap-")
    assert "## What I did" in body["output_markdown"]


def test_run_pipe_for_specific_day(api_client: TestClient):
    r = api_client.post("/pipes/run/day-recap", params={"day": FIXTURE_DAY})
    assert r.status_code == 200
    assert r.json()["output_path"].endswith(f"day-recap-{FIXTURE_DAY}.md")


def test_run_unknown_pipe_404(api_client: TestClient):
    assert api_client.post("/pipes/run/nope").status_code == 404


def test_run_pipe_writes_file_with_front_matter(api_client: TestClient, data_dir):
    api_client.post("/pipes/run/day-recap", params={"day": FIXTURE_DAY})
    path = data_dir / "output" / f"day-recap-{FIXTURE_DAY}.md"
    assert path.exists()
    text = path.read_text()
    assert text.startswith("---\n")
    assert "title: Day recap" in text
    assert "frame_count: 8" in text
    assert "trace_url:" in text
    assert "## Unfinished / to pick up" in text
    assert "## Standout" in text


def test_run_breakdown_pipe(api_client: TestClient):
    r = api_client.post("/pipes/run/time-breakdown", params={"day": FIXTURE_DAY})
    assert r.status_code == 200
    body = r.json()
    assert body["output_path"].endswith(f"time-breakdown-{FIXTURE_DAY}.md")
    assert "| Category | Minutes |" in body["output_markdown"]
    assert "Music" in body["output_markdown"]


# ---- /sessions ----

def _insert_session(db, *, player="vlc", wall_ms=1_000, pos=600_000_000,
                    title="Inception (2010)", source="file:///mnt/movies/Inception.mkv"):
    from heimdall.capture.sessions import SessionTracker

    t = SessionTracker()
    t.play(player, title=title, source=source, position_us=pos,
           length_us=7_200_000_000, wall_ms=wall_ms)
    return db.insert_watch_session(t.stop(player, position_us=pos + 300_000_000,
                                          wall_ms=wall_ms + 129_000))


def test_sessions_list_shape(api_client: TestClient, db):
    _insert_session(db)
    r = api_client.get("/sessions")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"total", "items"}
    assert body["total"] == 1
    item = body["items"][0]
    for key in ("id", "player", "media_title", "media_source", "media_id",
                "ts_start", "ts_end", "pos_start", "pos_end", "length", "ranges"):
        assert key in item
    assert item["ranges"] == [[600_000_000, 900_000_000]]
    assert item["media_source"] == "file:///mnt/movies/Inception.mkv"
    assert datetime.fromisoformat(item["ts_start"]).tzinfo is not None
    assert datetime.fromisoformat(item["ts_end"]).tzinfo is not None


def test_sessions_newest_first(api_client: TestClient, db):
    _insert_session(db, wall_ms=1_000)
    _insert_session(db, player="sidra", wall_ms=200_000)
    items = api_client.get("/sessions").json()["items"]
    assert [it["player"] for it in items] == ["sidra", "vlc"]


def test_sessions_detail_includes_ranges_and_404(api_client: TestClient, db):
    _insert_session(db)
    sid = api_client.get("/sessions").json()["items"][0]["id"]
    r = api_client.get(f"/sessions/{sid}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["ranges"] == [[600_000_000, 900_000_000]]
    assert detail["pos_start"] == 600_000_000
    assert api_client.get("/sessions/999999").status_code == 404


def test_sessions_filters_and_pagination(api_client: TestClient, db):
    _insert_session(db, wall_ms=1_000)
    _insert_session(db, player="sidra", wall_ms=200_000)
    body = api_client.get("/sessions", params={"player": "vlc"}).json()
    assert body["total"] == 1

    start_iso = ts_to_iso(50_000)
    body = api_client.get("/sessions", params={"start": start_iso}).json()
    assert body["total"] == 1
    assert body["items"][0]["player"] == "sidra"
    end_iso = ts_to_iso(5_000)
    body = api_client.get("/sessions", params={"end": end_iso}).json()
    assert body["total"] == 1

    body = api_client.get("/sessions", params={"limit": 1, "offset": 1}).json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert api_client.get("/sessions", params={"limit": 0}).status_code == 422
    assert api_client.get("/sessions", params={"start": "not-a-date"}).status_code == 422


def test_sessions_live_row_renders_null_ts_end(api_client: TestClient, db):
    """An in-progress session is exposed as live: 1 with ts_end: null (#35+)."""
    db.insert_live_session(
        "vlc", "Inception (2010)", "file:///mnt/movies/Inception.mkv", None,
        ts_start=1_000, pos_start=600_000_000, length=7_200_000_000,
        ranges=[[600_000_000, 630_000_000]],
    )
    body = api_client.get("/sessions").json()
    item = body["items"][0]
    assert item["live"] == 1
    assert item["ts_end"] is None
    assert datetime.fromisoformat(item["ts_start"]).tzinfo is not None


# ---- /sessions/{id}/transcript (lazy ASR, #40) ----

def _wait_for_transcript(client, sid, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/sessions/{sid}/transcript")
        if r.status_code == 200:
            return r
        time.sleep(0.05)
    raise AssertionError(f"transcript never became ready (last status {r.status_code})")


def test_session_transcript_404(api_client):
    assert api_client.get("/sessions/999999/transcript").status_code == 404


def test_session_transcript_returns_stored_captions(api_client, db):
    sid = _insert_session(db)
    db.update_session_transcript(sid, cues_json="[]",
                                 transcript="never gonna give you up",
                                 transcript_source="captions")
    r = api_client.get(f"/sessions/{sid}/transcript")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == sid
    assert body["transcript"] == "never gonna give you up"
    assert body["transcript_source"] == "captions"
    assert body["cues_json"] == "[]"


def test_session_transcript_409_while_live(api_client, db):
    row_id = db.insert_live_session(
        "vlc", "Inception (2010)", "file:///mnt/movies/Inception.mkv", None,
        ts_start=1_000, pos_start=600_000_000, length=7_200_000_000, ranges=[],
    )
    r = api_client.get(f"/sessions/{row_id}/transcript")
    assert r.status_code == 409


def test_session_transcript_422_without_local_file(api_client, db):
    sid = _insert_session(db, source="https://youtube.com/watch?v=dQw4w9WgXcQ")
    r = api_client.get(f"/sessions/{sid}/transcript")
    assert r.status_code == 422
    assert "local media file" in r.json()["detail"]


def test_session_transcript_lazy_asr_flow(api_client, db, monkeypatch):
    from heimdall.capture.asr import AsrEngine

    sid = _insert_session(db)
    extracted = []

    def fake_extract(path, ranges):
        extracted.append((path, ranges))
        return b"\x00" * 64

    monkeypatch.setattr("heimdall.capture.asr.extract_ranges_pcm", fake_extract)
    monkeypatch.setattr(AsrEngine, "transcribe", lambda self, pcm: "I watched the movie")

    r = api_client.get(f"/sessions/{sid}/transcript")
    assert r.status_code == 202
    body = r.json()
    assert body["session_id"] == sid
    assert body["job"]["status"] in ("queued", "running")

    r = _wait_for_transcript(api_client, sid)
    assert r.status_code == 200
    body = r.json()
    assert body["transcript"] == "I watched the movie"
    assert body["transcript_source"] == "asr"
    assert body["cues_json"] is None
    assert extracted == [("/mnt/movies/Inception.mkv", [[600_000_000, 900_000_000]])]

    # completed results are cached: a repeat call returns instantly, no re-run
    r = api_client.get(f"/sessions/{sid}/transcript")
    assert r.status_code == 200
    assert len(extracted) == 1

    # the ASR transcript is searchable through the merged FTS surface
    hits = api_client.get("/search", params={"q": "watched", "kind": "session"}).json()
    assert any(it["id"] == sid for it in hits["items"])


# ---- /media/live (extension stream, #44) ----

def test_media_live_ingests_stream_row(api_client: TestClient, db):
    """POST /media/live lands a tab's reading where the resolver reads it."""
    r = api_client.post("/media/live", json={
        "title": "Rick Astley - Never Gonna Give You Up - YouTube",
        "href": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "current_time_us": 900_000_000,
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    rows = db.latest_media_stream()
    assert len(rows) == 1
    assert rows[0]["href"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert rows[0]["current_time_us"] == 900_000_000


def test_media_live_requires_href(api_client: TestClient, db):
    assert api_client.post("/media/live", json={"title": "x"}).status_code == 422
    assert api_client.post("/media/live", json={
        "title": "x", "href": "y", "current_time_us": "nope",
    }).status_code == 422
    assert db.latest_media_stream() == []


# ---- /status ----

def test_status(api_client: TestClient):
    r = api_client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert body["server"]["status"] == "ok"
    assert body["db"]["frames_today"] == 8
    assert body["capture"]["alive"] is False
    assert body["llama"]["reachable"] is True
    assert body["tracing"]["enabled"] is False
    assert body["tracing"]["reason"] == "LANGFUSE_* env vars unset"
    assert body["pipes"]["last_runs"] == {"day-recap": None, "time-breakdown": None}


def test_status_reports_extraction_mode(data_dir):
    cfg = Config(data_dir=data_dir)
    cfg.capture.extraction = "a11y"
    cfg.capture.window_class_merge = {"code": "ocr_also"}
    app = create_app(cfg, db_path=data_dir / "data.db",
                     llm_transport=mock_llm_response(RECAP_COMPLETION))
    with TestClient(app) as client:
        body = client.get("/status").json()
    assert body["capture"]["extraction"] == "a11y"
    assert body["capture"]["ocr_also"] == ["code"]


def test_status_media_players_injected(data_dir):
    cfg = Config(data_dir=data_dir)
    app = create_app(
        cfg, db_path=data_dir / "data.db",
        llm_transport=mock_llm_response(RECAP_COMPLETION),
        list_players=lambda: [{"name": "mpv", "status": "playing"},
                              {"name": "chromium", "status": "stopped"}],
    )
    with TestClient(app) as client:
        players = client.get("/status").json()["capture"]["players"]
    assert players == [{"name": "mpv", "status": "playing"},
                       {"name": "chromium", "status": "stopped"}]


def test_status_last_session_and_asr_pending(api_client, db):
    from heimdall.capture.sessions import WatchSession

    db.insert_watch_session(WatchSession(
        player="vlc", media_title="Inception (2010)",
        media_source="file:///mnt/movies/Inception.mkv", media_id=None,
        ts_start=1_700_000_000_000, ts_end=1_700_001_000_000,
        pos_start=0, pos_end=7_200_000_000, length=8_400_000_000, ranges=[[0, 7_200_000_000]],
    ))
    body = api_client.get("/status").json()
    last = body["media"]["last_session"]
    assert last["media_title"] == "Inception (2010)"
    assert last["player"] == "vlc"
    assert last["media_source"] == "file:///mnt/movies/Inception.mkv"
    assert last["ts_end"] == 1_700_001_000_000
    assert body["asr"] == {"queued": 0, "running": 0, "failed": 0, "items": []}


# ---- POST /capture (manual capture) ----

def test_manual_capture_returns_frame(tmp_path, monkeypatch):
    """Writes capture.request, acks the seeded rid, returns the frame row."""
    import json
    import uuid

    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg, db_path=tmp_path / "data.db",
                     llm_transport=mock_llm_response(RECAP_COMPLETION))
    monkeypatch.setattr("heimdall.api.routers.uuid.uuid4",
                        lambda: uuid.UUID(int=1))
    monkeypatch.setattr("heimdall.api.routers.time.sleep", lambda _: None)

    with TestClient(app) as client:
        db = client.app.state.db
        frame_id = db.insert_frame({
            "ts": 1_700_000_000_000, "monitor": 0, "workspace": 2,
            "window_class": "kitty", "window_title": "manual",
            "fullscreen": 0, "trigger": "manual", "image_path": "frames/x.jpg",
            "image_bytes": 4, "ocr_text": "hello manual capture", "ocr_sec": 1.0,
            "a11y_text": None, "a11y_json": None, "ocr_engine": None,
        })
        (cfg.data_path / "capture.ack").write_text(json.dumps(
            {"id": uuid.UUID(int=1).hex, "status": "ok", "frame_id": frame_id}))

        r = client.post("/capture")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == frame_id
        assert body["window_class"] == "kitty"
        assert body["ocr_text"] == "hello manual capture"
        assert (cfg.data_path / "capture.request").exists()


def test_manual_capture_503_when_daemon_silent(tmp_path, monkeypatch):
    import itertools

    monkeypatch.setattr("heimdall.api.routers.time.sleep", lambda _: None)
    ticks = itertools.count()
    monkeypatch.setattr("heimdall.api.routers.time.time",
                        lambda: next(ticks))  # monotonic; advances the 30s deadline
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg, db_path=tmp_path / "data.db",
                     llm_transport=mock_llm_response(RECAP_COMPLETION))
    with TestClient(app) as client:
        r = client.post("/capture")
    assert r.status_code == 503
    assert "capture daemon not responding" in r.json()["detail"]
