"""v1 -> v2 startup migration: additive columns + FTS rebuild, no data loss.

The live DB is v1 (tesseract-era); heimdall v2 applies this migration on every
startup (daemon and API both go through init_db). Existing rows and columns are
untouched; frames_fts is rebuilt to index a11y_text.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from heimdall.db import Database, init_db

V1_SCHEMA = """
CREATE TABLE frames (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    monitor INTEGER,
    workspace INTEGER,
    window_class TEXT,
    window_title TEXT,
    fullscreen INTEGER,
    trigger TEXT,
    image_path TEXT NOT NULL,
    image_bytes INTEGER NOT NULL,
    ocr_text TEXT,
    ocr_sec REAL
);
CREATE VIRTUAL TABLE frames_fts USING fts5(
    ocr_text, window_title, window_class,
    content='frames', content_rowid='id'
);
CREATE TRIGGER frames_ai AFTER INSERT ON frames BEGIN
    INSERT INTO frames_fts(rowid, ocr_text, window_title, window_class)
    VALUES (new.id, new.ocr_text, new.window_title, new.window_class);
END;
CREATE TRIGGER frames_au AFTER UPDATE ON frames BEGIN
    INSERT INTO frames_fts(frames_fts, rowid, ocr_text, window_title, window_class)
    VALUES ('delete', old.id, old.ocr_text, old.window_title, old.window_class);
    INSERT INTO frames_fts(rowid, ocr_text, window_title, window_class)
    VALUES (new.id, new.ocr_text, new.window_title, new.window_class);
END;
CREATE TRIGGER frames_ad AFTER DELETE ON frames BEGIN
    INSERT INTO frames_fts(frames_fts, rowid, ocr_text, window_title, window_class)
    VALUES ('delete', old.id, old.ocr_text, old.window_title, old.window_class);
END;
"""


def _make_v1_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(V1_SCHEMA)
    conn.execute(
        "INSERT INTO frames (ts, monitor, workspace, window_class, window_title,"
        " fullscreen, trigger, image_path, image_bytes, ocr_text, ocr_sec)"
        " VALUES (1000, 0, 2, 'firefox', 'old page', 0, 'activewindow',"
        " 'frames/2026/08/02/0.jpg', 10, 'old ocr text', 3.5)"
    )
    conn.commit()
    conn.close()


def _columns(path: Path, table: str) -> dict[str, str]:
    conn = sqlite3.connect(path)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    conn.close()
    return {r[1]: r[2] for r in rows}


def _fts_ddl(path: Path) -> str:
    conn = sqlite3.connect(path)
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='frames_fts'").fetchone()[0]
    conn.close()
    return sql


def test_migration_adds_v2_columns_and_preserves_rows(tmp_path):
    path = tmp_path / "v1.db"
    _make_v1_db(path)
    init_db(path)

    frames = _columns(path, "frames")
    assert frames["a11y_text"] == "TEXT"
    assert frames["a11y_json"] == "TEXT"
    assert frames["ocr_engine"] == "TEXT"
    assert frames["ocr_text"] == "TEXT"  # untouched v1 column

    conn = sqlite3.connect(path)
    row = conn.execute("SELECT id, window_title, ocr_text, ocr_sec FROM frames").fetchone()
    conn.close()
    assert row == (1, "old page", "old ocr text", 3.5)


def test_migration_rebuilds_fts_to_index_a11y_text(tmp_path):
    path = tmp_path / "v1.db"
    _make_v1_db(path)
    init_db(path)

    fts = _fts_ddl(path)
    assert "a11y_text" in fts
    assert "content='frames'" in fts

    db = Database(path)
    # a fresh a11y-won insert is indexed
    db.insert_frame(dict(ts=2000, monitor=0, workspace=2, window_class="code",
                         window_title="x.py", fullscreen=0, trigger="activewindow",
                         image_path="frames/2026/08/02/1.jpg", image_bytes=1,
                         a11y_text="event loop debounce"))
    total, _ = db.search("debounce")
    assert total == 1

    # an existing row updated to a11y text is indexed too
    db.set_frame_extraction(1, a11y_text="old page now has a11y content")
    total, items = db.search("now has a11y")
    assert total == 1
    assert items[0]["id"] == 1


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "v1.db"
    _make_v1_db(path)
    init_db(path)
    conn = sqlite3.connect(path)
    n_triggers = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'frames_%'").fetchone()[0]
    conn.close()
    init_db(path)  # second startup
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT ocr_text FROM frames WHERE id=1").fetchone()[0]
    n_triggers2 = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'frames_%'").fetchone()[0]
    conn.close()
    assert row == "old ocr text"
    assert n_triggers == n_triggers2


def test_fresh_v2_db_needs_no_migration(tmp_path):
    path = tmp_path / "fresh.db"
    init_db(path)
    frames = _columns(path, "frames")
    assert "a11y_text" in frames
    assert "a11y_json" in frames
    assert "ocr_engine" in frames
    assert "a11y_text" in _fts_ddl(path)


def test_v1_migration_creates_watch_sessions_tables(tmp_path):
    """v2 #35: the startup migration adds watch_sessions + FTS on v1 DBs too."""
    path = tmp_path / "v1.db"
    _make_v1_db(path)
    init_db(path)
    conn = sqlite3.connect(path)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'watch_sessions%'")}
    cols = {r[1] for r in conn.execute("PRAGMA table_info(watch_sessions)")}
    conn.close()
    assert "watch_sessions" in names
    assert "watch_sessions_fts" in names
    assert "live" in cols


def test_v2_migration_adds_live_column_to_existing_watch_sessions(tmp_path):
    """Pre-live watch_sessions (already migrated, v2-era) gain `live` = 0 in
    place; existing rows are preserved."""
    path = tmp_path / "prelive.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE watch_sessions (
            id INTEGER PRIMARY KEY,
            player TEXT NOT NULL,
            media_title TEXT,
            media_source TEXT,
            media_id TEXT,
            ts_start INTEGER NOT NULL,
            ts_end INTEGER NOT NULL,
            pos_start INTEGER NOT NULL,
            pos_end INTEGER NOT NULL,
            length INTEGER NOT NULL,
            ranges TEXT NOT NULL
        );
        INSERT INTO watch_sessions (player, media_title, media_source, media_id,
            ts_start, ts_end, pos_start, pos_end, length, ranges)
        VALUES ('vlc', 'Inception (2010)', 'file:///mnt/movies/Inception.mkv', NULL,
                1000, 2000, 600000000, 900000000, 7200000000,
                '[[600000000,900000000]]');
    """)
    conn.commit()
    conn.close()

    init_db(path)

    conn = sqlite3.connect(path)
    cols = {r[1]: (r[2], r[3], r[4]) for r in
            conn.execute("PRAGMA table_info(watch_sessions)")}
    live = conn.execute("SELECT live FROM watch_sessions").fetchone()[0]
    ts_end = conn.execute("SELECT ts_end FROM watch_sessions").fetchone()[0]
    conn.close()
    assert cols["live"] == ("INTEGER", 1, "0")  # NOT NULL DEFAULT 0
    assert live == 0  # existing rows preserved, backfilled with 0
    assert ts_end == 2000


def test_migration_adds_transcript_and_rebuilds_watch_fts(tmp_path):
    """Pre-#38 watch_sessions (live column, but no cues_json/transcript and a
    3-column watch_sessions_fts) gains the columns and an FTS rebuild that
    keeps existing rows searchable."""
    path = tmp_path / "pretranscript.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE watch_sessions (
            id INTEGER PRIMARY KEY,
            player TEXT NOT NULL,
            media_title TEXT,
            media_source TEXT,
            media_id TEXT,
            ts_start INTEGER NOT NULL,
            ts_end INTEGER NOT NULL,
            pos_start INTEGER NOT NULL,
            pos_end INTEGER NOT NULL,
            length INTEGER NOT NULL,
            ranges TEXT NOT NULL,
            live INTEGER NOT NULL DEFAULT 0
        );
        CREATE VIRTUAL TABLE watch_sessions_fts USING fts5(
            media_title, media_source,
            content='watch_sessions', content_rowid='id',
            tokenize='porter unicode61'
        );
        CREATE TRIGGER watch_sessions_ai AFTER INSERT ON watch_sessions BEGIN
            INSERT INTO watch_sessions_fts(rowid, media_title, media_source)
            VALUES (new.id, new.media_title, new.media_source);
        END;
        CREATE TRIGGER watch_sessions_ad AFTER DELETE ON watch_sessions BEGIN
            INSERT INTO watch_sessions_fts(watch_sessions_fts, rowid, media_title, media_source)
            VALUES ('delete', old.id, old.media_title, old.media_source);
        END;
        CREATE TRIGGER watch_sessions_au AFTER UPDATE ON watch_sessions BEGIN
            INSERT INTO watch_sessions_fts(watch_sessions_fts, rowid, media_title, media_source)
            VALUES ('delete', old.id, old.media_title, old.media_source);
            INSERT INTO watch_sessions_fts(rowid, media_title, media_source)
            VALUES (new.id, new.media_title, new.media_source);
        END;
        INSERT INTO watch_sessions (player, media_title, media_source, media_id,
            ts_start, ts_end, pos_start, pos_end, length, ranges, live)
        VALUES ('chromium.instance1', 'Rick Astley - Never Gonna Give You Up',
                'https://youtube.com/watch?v=dQw4w9WgXcQ', 'dQw4w9WgXcQ',
                1000, 2000, 0, 5000000, 213000000, '[[0,5000000]]', 0);
    """)
    conn.commit()
    conn.close()

    init_db(path)

    cols = _columns(path, "watch_sessions")
    assert cols["cues_json"] == "TEXT"
    assert cols["transcript"] == "TEXT"
    conn = sqlite3.connect(path)
    watch_fts = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='watch_sessions_fts'").fetchone()[0]
    conn.close()
    assert "transcript" in watch_fts

    db = Database(path)
    row_id = db.list_watch_sessions()[1][0]["id"]
    db.update_session_transcript(row_id, cues_json="[]",
                                 transcript="never gonna give you up")
    total, items = db.search_watch_sessions("gonna give you up")
    assert total == 1
    assert items[0]["id"] == row_id
    init_db(path)  # idempotent: second startup is a no-op


def test_migration_relaxes_legacy_ocr_text_not_null(tmp_path):
    """Live v1 DBs with ocr_text NOT NULL accept a11y-blind NULL inserts."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE frames (
            id INTEGER PRIMARY KEY,
            ts INTEGER NOT NULL,
            monitor INTEGER,
            workspace INTEGER,
            window_class TEXT,
            window_title TEXT,
            fullscreen INTEGER,
            trigger TEXT,
            image_path TEXT NOT NULL,
            image_bytes INTEGER NOT NULL,
            ocr_text TEXT NOT NULL DEFAULT '',
            ocr_sec REAL
        );
        CREATE INDEX idx_frames_ts ON frames(ts);
        """
    )
    conn.execute(
        "INSERT INTO frames (ts, monitor, workspace, window_class, window_title,"
        " fullscreen, trigger, image_path, image_bytes, ocr_text, ocr_sec)"
        " VALUES (1000, 0, 2, 'kitty', 'old terminal', 0, 'activewindow',"
        " 'frames/2026/08/02/0.jpg', 10, 'old ocr text', 3.5)"
    )
    conn.commit()
    conn.close()

    init_db(path)
    conn = sqlite3.connect(path)
    notnull = conn.execute(
        "SELECT \"notnull\" FROM pragma_table_info('frames') WHERE name='ocr_text'"
    ).fetchone()[0]
    row = conn.execute(
        "SELECT id, window_title, ocr_text FROM frames WHERE id=1").fetchone()
    conn.close()
    assert notnull == 0
    assert row == (1, "old terminal", "old ocr text")

    db = Database(path)
    db.insert_frame(dict(ts=2000, monitor=0, workspace=2, window_class="kitty",
                         window_title="new terminal", fullscreen=0,
                         trigger="activewindow", image_path="frames/2026/08/02/1.jpg",
                         image_bytes=1, a11y_text="git status"))
    assert db.search("git status")[0] == 1
    init_db(path)  # idempotent: second startup is a no-op
    conn = sqlite3.connect(path)
    notnull = conn.execute(
        "SELECT \"notnull\" FROM pragma_table_info('frames') WHERE name='ocr_text'"
    ).fetchone()[0]
    conn.close()
    assert notnull == 0


def test_snippet_prefers_a11y_but_falls_back_to_ocr(db):
    """a11y-won frames snippet from a11y_text; ocr-won frames from ocr_text."""
    a11y_total, a11y_items = db.search("debounce")
    assert a11y_total >= 1
    for it in a11y_items:
        assert it["snippet"] is not None
    _, ocr_items = db.search("rick astley")
    for it in ocr_items:
        assert "rick" in it["snippet"]
        assert "astley" in it["snippet"]


def test_search_ranks_title_above_both_text_sources(db):
    """Titles keep weight 2.0 over a11y/ocr text weight 1.0."""
    from conftest import FIXTURE_DAY
    from heimdall.timeutil import day_bounds
    start, _ = day_bounds(FIXTURE_DAY)
    db.insert_frame(dict(ts=start + 200 * 60_000, monitor=0, workspace=2,
                         window_class="kitty", window_title="checkpointers only in title",
                         fullscreen=0, trigger="keepalive", image_path="x.jpg",
                         image_bytes=1, ocr_text="", a11y_text=""))
    db.insert_frame(dict(ts=start + 210 * 60_000, monitor=0, workspace=2,
                         window_class="kitty", window_title="",
                         fullscreen=0, trigger="keepalive", image_path="y.jpg",
                         image_bytes=1, ocr_text="",
                         a11y_text="checkpointers only in a11y"))
    total, items = db.search("checkpointers")
    scores = {it["window_title"]: it["score"] for it in items}
    assert scores["checkpointers only in title"] < scores[""]
