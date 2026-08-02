"""HTTP API tests (primary seam): shapes, filters, pagination, pipe run contract."""

from __future__ import annotations

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


# ---- /search ----

def test_search_shape(api_client: TestClient):
    r = api_client.get("/search", params={"q": "youtube"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"total", "items"}
    item = body["items"][0]
    assert set(item) == {"id", "ts", "window_class", "window_title", "workspace",
                         "image_path", "snippet", "score"}
    assert item["image_path"].startswith("frames/")
    assert body["total"] == 1


def test_search_requires_q(api_client: TestClient):
    assert api_client.get("/search").status_code == 422


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
                "fullscreen", "trigger", "image_path", "image_bytes", "ocr_text", "ocr_sec"):
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


# ---- /status ----

def test_status(api_client: TestClient):
    r = api_client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert body["server"]["status"] == "ok"
    assert body["db"]["frames_today"] == 8
    assert body["capture"]["alive"] is False
    assert body["llama"]["reachable"] is True
    assert body["pipes"]["last_runs"] == {"day-recap": None, "time-breakdown": None}
