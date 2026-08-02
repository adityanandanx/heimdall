"""Shared test fixtures: a small hand-built frames/tracks/events set + API client.

The fixture day is deterministic; timestamps are placed at known offsets inside
the local-day window so day-scoped pipes and span math are reproducible.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from heimdall.api.app import create_app
from heimdall.capture.spans import track_playing_ms
from heimdall.config import Config
from heimdall.db import Database, initialize
from heimdall.timeutil import day_bounds

FIXTURE_DAY = "2026-08-02"

# (offset_min, window_class, window_title, ocr_text, trigger)
FIXTURE_FRAMES = [
    (0, "kitty", "zsh — htop", "terminal processes", "keepalive"),
    (5, "code", "capture.py — heimdall", "event loop debounce and throttle", "activewindow"),
    (20, "firefox", "LangGraph docs — checkpointers", "reading the checkpointers docs", "activewindow"),
    (35, "firefox", "youtube.com/watch?v=dQw4w9WgXcQ", "never gonna give you up rick astley", "windowtitle"),
    (50, "mpv", "Inception (2010)", "movie about dreams inside dreams", "activewindow"),
    (65, "code", "leetcode.com/problems/two-sum", "hash map solution o of n", "activewindow"),
    (80, "firefox", "linkedin.com/jobs", "staff engineer roles", "activewindow"),
    (90, "kitty", "~ — terminal", "installing packages with pacman", "keepalive"),
]


def build_day_db(db_path: Path, day: str = FIXTURE_DAY) -> Database:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    initialize(db_path)
    db = Database(db_path)
    start_ms, _ = day_bounds(day)
    for i, (off, cls, title, ocr, trig) in enumerate(FIXTURE_FRAMES):
        rel = f"frames/2026/08/02/{i}.jpg"
        image = db_path.parent / rel
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"\xff\xd8\xff\xe0" + f"fixture{i}".encode())
        db.insert_frame({
            "ts": start_ms + off * 60_000,
            "monitor": "eDP-1",
            "workspace": "2:2",
            "window_class": cls,
            "window_title": title,
            "fullscreen": 0,
            "trigger": trig,
            "image_path": rel,
            "image_bytes": len(image.read_bytes()),
            "ocr_text": ocr,
            "ocr_sec": 4.0,
        })
    # sidra playing 00:00 -> 10:00 (exact music span = 10 min)
    db.insert_track(ts=start_ms + 0, player="sidra", artist="Tycho", title="Awake",
                    album=None, status="playing")
    db.insert_track(ts=start_ms + 10 * 60_000, player="sidra", artist="Tycho", title="Awake",
                    album=None, status="paused")
    return db


def mock_llm_response(completions) -> httpx.MockTransport:
    """MockTransport answering /v1/chat/completions.

    `completions` is a dict {substring_of_user_prompt: completion}; the first
    matching key wins, otherwise the first completion is returned.
    """
    if isinstance(completions, dict) and all(isinstance(v, dict) for v in completions.values()):
        routes = list(completions.items())
    else:
        routes = [("", completions)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/completions":
            body = json.loads(request.content)
            user = body["messages"][-1]["content"]
            completion = next((comp for m, comp in routes if m == ""), routes[0][1])
            for marker, comp in routes:
                if marker and marker in user:
                    completion = comp
                    break
            return httpx.Response(200, json={
                "choices": [{"message": {"role": "assistant",
                                         "content": json.dumps(completion)}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            })
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


RECAP_COMPLETION = {
    "date": "2026-08-02",
    "summary": "A focused day of building heimdall and watching a movie.",
    "accomplishments": ["Finished the event loop", "Shipped the FTS5 schema"],
    "unfinished": ["Two Sum still half-done", "Job applications in progress"],
    "standout": ["Learned about checkpointers"],
}

BREAKDOWN_COMPLETION = {
    "categories": [
        {"category": "Building projects", "minutes": 30, "evidence": "code windows"},
        {"category": "Researching", "minutes": 20, "evidence": "LangGraph docs"},
        {"category": "YouTube", "minutes": 15, "evidence": "rick astley"},
        {"category": "DSA", "minutes": 15, "evidence": "two-sum"},
        {"category": "Job applications", "minutes": 10, "evidence": "linkedin"},
    ],
}


@pytest.fixture
def db_path_tmp(tmp_path: Path):
    return tmp_path / "fresh.db"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def config(data_dir: Path) -> Config:
    cfg = Config(data_dir=data_dir)
    return cfg


@pytest.fixture
def db(data_dir: Path) -> Database:
    return build_day_db(data_dir / "data.db")


@pytest.fixture
def api_client(db: Database, data_dir: Path) -> TestClient:
    cfg = Config(data_dir=data_dir)
    app = create_app(
        cfg, db_path=db.path,
        llm_transport=mock_llm_response({
            "span table": BREAKDOWN_COMPLETION,
            "": RECAP_COMPLETION,
        }),
    )
    with TestClient(app) as client:
        yield client
