"""DB schema + FTS5 fixture tests (first build step)."""

from __future__ import annotations

import sqlite3

from heimdall.db import Database, init_db
from heimdall.timeutil import day_bounds

from conftest import FIXTURE_DAY, build_day_db


def _tables(db_path) -> set[str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()
    conn.close()
    return {r[0] for r in rows}


def test_schema_creates_all_tables(db_path_tmp):
    init_db(db_path_tmp)
    tables = _tables(db_path_tmp)
    assert {"frames", "tracks", "events", "frames_fts"} <= tables


def _column_types(db_path, table) -> dict[str, str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    conn.close()
    return {r[1]: r[2] for r in rows}


def test_frames_schema_matches_locked_ddl(db_path_tmp):
    """The schema is the locked v1 DDL (spec #6): monitor/workspace are
    INTEGER, window_class is nullable TEXT, tracks has no NOT NULL columns."""
    init_db(db_path_tmp)
    frames = _column_types(db_path_tmp, "frames")
    assert frames["monitor"] == "INTEGER"
    assert frames["workspace"] == "INTEGER"
    assert frames["window_class"] == "TEXT"
    assert frames["fullscreen"] == "INTEGER"
    assert frames["trigger"] == "TEXT"
    assert frames["ocr_text"] == "TEXT"
    tracks = _column_types(db_path_tmp, "tracks")
    assert tracks["player"] == "TEXT"
    assert tracks["title"] == "TEXT"


def test_frames_fts_is_external_content(db_path_tmp):
    init_db(db_path_tmp)
    conn = sqlite3.connect(db_path_tmp)
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='frames_fts'").fetchone()[0]
    assert "content='frames'" in sql
    assert "content_rowid='id'" in sql
    conn.close()


def test_fts_syncs_on_insert(tmp_path):
    db = build_day_db(tmp_path / "data.db")
    total, items = db.search("rick astley")
    assert total == 1
    assert items[0]["window_title"].startswith("youtube.com")
    assert "**rick**" in items[0]["snippet"] and "**astley**" in items[0]["snippet"]


def test_fts_syncs_on_delete(db):
    _, items = db.search("rick astley")
    target = items[0]
    conn = db.open()
    conn.execute("DELETE FROM frames WHERE id = ?", (target["id"],))
    conn.commit()
    conn.close()
    total, _ = db.search("rick astley")
    assert total == 0


def test_search_boosts_title_over_ocr(db):
    start, _ = day_bounds(FIXTURE_DAY)
    db.insert_frame(dict(ts=start + 200 * 60_000, monitor=0, workspace=2,
                         window_class="kitty", window_title="checkpointers only in title",
                         fullscreen=0, trigger="keepalive", image_path="x.jpg",
                         image_bytes=1, ocr_text="", ocr_sec=1.0))
    db.insert_frame(dict(ts=start + 210 * 60_000, monitor=0, workspace=2,
                         window_class="kitty", window_title="",
                         fullscreen=0, trigger="keepalive", image_path="y.jpg",
                         image_bytes=1, ocr_text="checkpointers only in ocr", ocr_sec=1.0))
    total, items = db.search("checkpointers")
    assert total >= 3
    scores = {it["window_title"]: it["score"] for it in items}
    # title match (weight 2.0) ranks above OCR-only match (weight 1.0)
    assert scores["checkpointers only in title"] < scores[""]


def test_search_filters_and_pagination(db):
    start, end = day_bounds(FIXTURE_DAY)
    total, items = db.search("youtube OR langgraph OR leetcode OR linkedin OR terminal",
                             window_class="firefox")
    assert total == 3
    assert {it["window_class"] for it in items} == {"firefox"}
    _, items2 = db.search("youtube OR langgraph OR leetcode OR linkedin OR terminal",
                          start=start + 15 * 60_000)
    assert {it["window_title"] for it in items2} >= {"LangGraph docs — checkpointers"}


def test_invalid_fts_query_raises(db):
    import pytest
    with pytest.raises(sqlite3.OperationalError):
        db.search("youtube AND (unclosed")


def test_frames_indexes_exist(db_path_tmp):
    init_db(db_path_tmp)
    conn = sqlite3.connect(db_path_tmp)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_frames_ts", "idx_frames_class_ts", "idx_frames_trigger", "idx_tracks_ts"} <= names
    conn.close()


def test_track_insert_or_ignore_duplicate_ts(db):
    db.insert_track(ts=42, player="sidra", artist="a", title="b", album=None, status="playing")
    db.insert_track(ts=42, player="sidra", artist="a", title="b", album=None, status="playing")
    assert len(db.list_tracks()) == 3


def test_events_roundtrip(db):
    db.insert_event(ts=1, raw="activewindow>>kitty,foo")
    db.insert_event(ts=2, raw="workspace>>2")
    conn = db.open()
    rows = conn.execute("SELECT ts, raw FROM events ORDER BY ts").fetchall()
    conn.close()
    assert [dict(r) for r in rows] == [
        {"ts": 1, "raw": "activewindow>>kitty,foo"},
        {"ts": 2, "raw": "workspace>>2"},
    ]
