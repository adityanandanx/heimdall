"""SQLite schema + access layer for heimdall.

Schema is the locked v1 DDL (spec ticket #6/#11): frames, tracks, events and
an FTS5 external-content table over frames with sync triggers. Timestamps are
UTC epoch ms. Images live on disk under the data dir, not in the DB.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from heimdall.capture.sessions import WatchSession

# The FTS table + sync triggers alone, so the v2 migration can drop/recreate
# them against an existing v1 frames table after the ALTER TABLE. SCHEMA
# composes this so the two can never drift.
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS frames_fts USING fts5(
    a11y_text, ocr_text, window_title, window_class,
    content='frames', content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS frames_ai AFTER INSERT ON frames BEGIN
    INSERT INTO frames_fts(rowid, a11y_text, ocr_text, window_title, window_class)
    VALUES (new.id, new.a11y_text, new.ocr_text, new.window_title, new.window_class);
END;

CREATE TRIGGER IF NOT EXISTS frames_ad AFTER DELETE ON frames BEGIN
    INSERT INTO frames_fts(frames_fts, rowid, a11y_text, ocr_text, window_title, window_class)
    VALUES ('delete', old.id, old.a11y_text, old.ocr_text, old.window_title, old.window_class);
END;

CREATE TRIGGER IF NOT EXISTS frames_au AFTER UPDATE ON frames BEGIN
    INSERT INTO frames_fts(frames_fts, rowid, a11y_text, ocr_text, window_title, window_class)
    VALUES ('delete', old.id, old.a11y_text, old.ocr_text, old.window_title, old.window_class);
    INSERT INTO frames_fts(rowid, a11y_text, ocr_text, window_title, window_class)
    VALUES (new.id, new.a11y_text, new.ocr_text, new.window_title, new.window_class);
END;
"""

# FTS over watch_sessions title/source (v2 #35) — a brand-new table on every DB,
# so it is created idempotently with SCHEMA and never needs a migration rebuild.
WATCH_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS watch_sessions_fts USING fts5(
    media_title, media_source,
    content='watch_sessions', content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS watch_sessions_ai AFTER INSERT ON watch_sessions BEGIN
    INSERT INTO watch_sessions_fts(rowid, media_title, media_source)
    VALUES (new.id, new.media_title, new.media_source);
END;

CREATE TRIGGER IF NOT EXISTS watch_sessions_ad AFTER DELETE ON watch_sessions BEGIN
    INSERT INTO watch_sessions_fts(watch_sessions_fts, rowid, media_title, media_source)
    VALUES ('delete', old.id, old.media_title, old.media_source);
END;

CREATE TRIGGER IF NOT EXISTS watch_sessions_au AFTER UPDATE ON watch_sessions BEGIN
    INSERT INTO watch_sessions_fts(watch_sessions_fts, rowid, media_title, media_source)
    VALUES ('delete', old.id, old.media_title, old.media_source);
    INSERT INTO watch_sessions_fts(rowid, media_title, media_source)
    VALUES (new.id, new.media_title, new.media_source);
END;
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,              -- UTC epoch ms
    monitor INTEGER,                  -- hyprctl monitor id
    workspace INTEGER,                -- hyprctl workspace id
    window_class TEXT,
    window_title TEXT,
    fullscreen INTEGER,
    trigger TEXT,                     -- activewindow|openwindow|workspace|fullscreen|windowtitle|keepalive|mpris
    image_path TEXT NOT NULL,         -- relative to the data dir
    image_bytes INTEGER NOT NULL,
    ocr_text TEXT,
    ocr_sec REAL,
    a11y_text TEXT,                   -- flattened tree text; the winner when set
    a11y_json TEXT,                   -- role/name/state structure, retained for retrieval
    ocr_engine TEXT                   -- 'rapid' when the OCR path was used (v2 #34)
);

CREATE TABLE IF NOT EXISTS tracks (
    ts INTEGER PRIMARY KEY,           -- UTC epoch ms
    player TEXT,
    artist TEXT,
    title TEXT,
    album TEXT,
    status TEXT                       -- playing|paused
);

CREATE TABLE IF NOT EXISTS events (
    ts INTEGER PRIMARY KEY,           -- UTC epoch ms; raw socket2 log
    raw TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watch_sessions (
    id INTEGER PRIMARY KEY,
    player TEXT NOT NULL,             -- raw MPRIS player (vlc, chromium.instance1)
    media_title TEXT,                 -- track title; Chromium title-only until CDP (#36)
    media_source TEXT,                -- xesam:url (VLC exact file path), None for Chromium
    media_id TEXT,                    -- NULL until the CDP player (#36)
    ts_start INTEGER NOT NULL,        -- UTC epoch ms; wall span excludes pauses
    ts_end INTEGER NOT NULL,
    pos_start INTEGER NOT NULL,       -- video-time microseconds
    pos_end INTEGER NOT NULL,
    length INTEGER NOT NULL,          -- video length in microseconds
    ranges TEXT NOT NULL,             -- JSON [[start_us, end_us], ...]; skipped segments excluded
    live INTEGER NOT NULL DEFAULT 0   -- 1 while the session is in progress
);

CREATE INDEX IF NOT EXISTS idx_frames_ts ON frames(ts);
CREATE INDEX IF NOT EXISTS idx_frames_class_ts ON frames(window_class, ts);
CREATE INDEX IF NOT EXISTS idx_frames_trigger ON frames(trigger);
CREATE INDEX IF NOT EXISTS idx_tracks_ts ON tracks(ts);
CREATE INDEX IF NOT EXISTS idx_watch_sessions_ts_start ON watch_sessions(ts_start);
CREATE INDEX IF NOT EXISTS idx_watch_sessions_player ON watch_sessions(player);
""" + FTS_SCHEMA + WATCH_FTS_SCHEMA

FRAME_COLS = (
    "id", "ts", "monitor", "workspace", "window_class", "window_title",
    "fullscreen", "trigger", "image_path", "image_bytes", "ocr_text", "ocr_sec",
    "a11y_text", "a11y_json", "ocr_engine",
)

SEARCH_COLS = ("id", "ts", "window_class", "window_title", "workspace", "image_path", "snippet", "score")

SESSION_COLS = (
    "id", "player", "media_title", "media_source", "media_id",
    "ts_start", "ts_end", "pos_start", "pos_end", "length", "ranges", "live",
)


def connect(path: str | os.PathLike) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(path: str | os.PathLike) -> None:
    """Create the DB at path (if missing), apply the schema and migrate v1.

    v1 DBs (tesseract-era) get the a11y columns added and frames_fts rebuilt to
    index a11y_text; existing rows are preserved. Idempotent on every startup.
    """
    conn = connect(path)
    conn.executescript(SCHEMA)
    _migrate_v2(conn)
    conn.commit()
    conn.close()


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Add the v2 columns to an existing v1 frames table and rebuild FTS.

    External-content FTS cannot add a column in place — it must be dropped and
    recreated, then repopulated with `rebuild`. Triggers are recreated with it.

    Some legacy live DBs were created with `ocr_text TEXT NOT NULL DEFAULT ''`;
    the v2 a11y-first path stores NULL for a11y-blind windows, so that column is
    relaxed (table rebuild) when it still carries the NOT NULL constraint.
    """
    info = {r[1]: r for r in conn.execute("PRAGMA table_info(frames)")}
    for col in ("a11y_text", "a11y_json", "ocr_engine"):
        if col not in info:
            conn.execute(f"ALTER TABLE frames ADD COLUMN {col} TEXT")
    ws_cols = {r[1] for r in conn.execute("PRAGMA table_info(watch_sessions)")}
    if "live" not in ws_cols:
        conn.execute("ALTER TABLE watch_sessions ADD COLUMN live INTEGER NOT NULL DEFAULT 0")
    need_frames_rebuild = bool(info["ocr_text"][3])  # notnull flag
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='frames_fts'"
    ).fetchone()
    fts_sql = row[0] if row else ""
    if "a11y_text" in fts_sql and not need_frames_rebuild:
        return
    if need_frames_rebuild:
        _rebuild_frames_table(conn)
    conn.execute("DROP TRIGGER IF EXISTS frames_ai")
    conn.execute("DROP TRIGGER IF EXISTS frames_ad")
    conn.execute("DROP TRIGGER IF EXISTS frames_au")
    conn.execute("DROP TABLE IF EXISTS frames_fts")
    conn.executescript(FTS_SCHEMA)
    conn.execute("INSERT INTO frames_fts(frames_fts) VALUES('rebuild')")


def _rebuild_frames_table(conn: sqlite3.Connection) -> None:
    """Recreate `frames` with the v2 shape (nullable ocr_text), preserving rows.

    SQLite cannot drop a NOT NULL constraint in place, so the table is rebuilt:
    the FTS triggers are dropped first, rows copied verbatim, then the FTS table
    is dropped and recreated with the new schema by _migrate_v2.
    """
    conn.executescript(
        """
        DROP TRIGGER IF EXISTS frames_ai;
        DROP TRIGGER IF EXISTS frames_ad;
        DROP TRIGGER IF EXISTS frames_au;
        CREATE TABLE frames_v2 (
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
            ocr_sec REAL,
            a11y_text TEXT,
            a11y_json TEXT,
            ocr_engine TEXT
        );
        INSERT INTO frames_v2 (id, ts, monitor, workspace, window_class,
            window_title, fullscreen, trigger, image_path, image_bytes,
            ocr_text, ocr_sec, a11y_text, a11y_json, ocr_engine)
        SELECT id, ts, monitor, workspace, window_class, window_title,
            fullscreen, trigger, image_path, image_bytes,
            ocr_text, ocr_sec, a11y_text, a11y_json, ocr_engine FROM frames;
        DROP TABLE frames;
        ALTER TABLE frames_v2 RENAME TO frames;
        CREATE INDEX IF NOT EXISTS idx_frames_ts ON frames(ts);
        CREATE INDEX IF NOT EXISTS idx_frames_class_ts ON frames(window_class, ts);
        CREATE INDEX IF NOT EXISTS idx_frames_trigger ON frames(trigger);
        """
    )


class Database:
    """Thread-safe access to one heimdall database.

    sqlite3 connections are cheap here (single user, local); the API opens one
    per request and the capture daemon owns its own. This class serializes the
    shared connection used by in-process callers (server, scheduler).
    """

    def __init__(self, path: str | os.PathLike):
        self.path = str(path)
        self._lock = threading.RLock()
        self.query_count = 0

    def open(self) -> sqlite3.Connection:
        return connect(self.path)

    @contextmanager
    def conn(self):
        """A fresh connection that is always closed, even on error."""
        connection = self.open()
        try:
            yield connection
        finally:
            connection.close()

    def size_bytes(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0

    # ---- frames ----

    def insert_frame(self, values: dict[str, Any]) -> int:
        with self._lock, self.conn() as conn:
            cur = conn.execute(
                "INSERT INTO frames (ts, monitor, workspace, window_class, window_title,"
                " fullscreen, trigger, image_path, image_bytes, ocr_text, ocr_sec,"
                " a11y_text, a11y_json, ocr_engine)"
                " VALUES (:ts, :monitor, :workspace, :window_class, :window_title,"
                " :fullscreen, :trigger, :image_path, :image_bytes, :ocr_text, :ocr_sec,"
                " :a11y_text, :a11y_json, :ocr_engine)",
                {**values,
                 "ocr_text": values.get("ocr_text"),
                 "ocr_sec": values.get("ocr_sec"),
                 "a11y_text": values.get("a11y_text"),
                 "a11y_json": values.get("a11y_json"),
                 "ocr_engine": values.get("ocr_engine")},
            )
            conn.commit()
            return cur.lastrowid

    def set_frame_extraction(self, frame_id: int, **updates: str | None) -> None:
        """Write extraction results for a frame; only the provided columns change.

        The worker passes the fields the winning source produced — a11y_text /
        a11y_json when the tree wins, a11y_text=None on an a11y-blind frame.
        ocr_* columns stay untouched unless passed (the #34 OCR path).
        """
        if not updates:
            return
        allowed = ("a11y_text", "a11y_json", "ocr_text", "ocr_sec", "ocr_engine")
        unknown = set(updates) - set(allowed)
        if unknown:
            raise ValueError(f"unknown extraction column(s): {sorted(unknown)}")
        sets = ", ".join(f"{col} = ?" for col in updates)
        with self._lock, self.conn() as conn:
            conn.execute(
                f"UPDATE frames SET {sets} WHERE id = ?",
                (*updates.values(), frame_id),
            )
            conn.commit()

    def list_frames(self, *, window_class: str | None = None, trigger: str | None = None,
                    start: int | None = None, end: int | None = None,
                    limit: int = 20, offset: int = 0) -> tuple[int, list[dict]]:
        self.query_count += 1
        where, params = self._frame_filters(window_class=window_class, trigger=trigger,
                                            start=start, end=end)
        with self._lock, self.conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM frames{where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT {', '.join(FRAME_COLS)} FROM frames{where}"
                " ORDER BY ts LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            items = [dict(r) for r in rows]
            return total, items

    def get_frame(self, frame_id: int) -> dict | None:
        self.query_count += 1
        with self._lock, self.conn() as conn:
            row = conn.execute(
                f"SELECT {', '.join(FRAME_COLS)} FROM frames WHERE id = ?", (frame_id,)
            ).fetchone()
            return dict(row) if row else None

    def frames_in_range(self, start: int | None = None, end: int | None = None,
                        limit: int | None = None) -> list[dict]:
        """All frames in [start, end) ordered by ts — used by the pipes."""
        self.query_count += 1
        clauses, params = [], []
        if start is not None:
            clauses.append("ts >= ?")
            params.append(start)
        if end is not None:
            clauses.append("ts < ?")
            params.append(end)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT {', '.join(FRAME_COLS)} FROM frames{where} ORDER BY ts"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._lock, self.conn() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def count_frames(self, start: int | None = None, end: int | None = None) -> int:
        self.query_count += 1
        where, params = self._frame_filters(start=start, end=end)
        with self._lock, self.conn() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM frames{where}", params).fetchone()[0]

    def _frame_filters(self, *, window_class=None, trigger=None, start=None, end=None) -> tuple[str, tuple]:
        clauses, params = [], []
        if window_class is not None:
            clauses.append("window_class = ?")
            params.append(window_class)
        if trigger is not None:
            clauses.append("trigger = ?")
            params.append(trigger)
        if start is not None:
            clauses.append("ts >= ?")
            params.append(start)
        if end is not None:
            clauses.append("ts <= ?")
            params.append(end)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, tuple(params)

    # ---- FTS5 search ----

    def search(self, query: str, *, window_class: str | None = None,
               start: int | None = None, end: int | None = None,
               limit: int = 20, offset: int = 0,
               order: str = "score") -> tuple[int, list[dict]]:
        """Full-text search over a11y/OCR text, window title and class.

        bm25 weights: a11y/OCR 1.0, title 2.0, class 1.0 (titles are cleaner
        than either text source). snippet comes from the winner — a11y_text
        when the tree won, else ocr_text — with `**` highlight markers.
        `order="ts"` sorts newest-first instead of by bm25 score (the #37
        merged-search timeline). Raises sqlite3.OperationalError on an invalid
        FTS5 MATCH.
        """
        self.query_count += 1
        where, params = [], []
        where.append("frames_fts MATCH ?")
        params.append(query)
        if window_class is not None:
            where.append("f.window_class = ?")
            params.append(window_class)
        if start is not None:
            where.append("f.ts >= ?")
            params.append(start)
        if end is not None:
            where.append("f.ts <= ?")
            params.append(end)
        order_by = "f.ts DESC" if order == "ts" else "score"
        sql = (
            "SELECT f.id, f.ts, f.window_class, f.window_title, f.workspace, f.image_path,"
            " COALESCE(snippet(frames_fts, 0, '**', '**', ' … ', 14),"
            "          snippet(frames_fts, 1, '**', '**', ' … ', 14)) AS snippet,"
            " bm25(frames_fts, 1.0, 1.0, 2.0, 1.0) AS score"
            " FROM frames_fts JOIN frames f ON f.id = frames_fts.rowid"
            f" WHERE {' AND '.join(where)} ORDER BY {order_by}"
            " LIMIT ? OFFSET ?"
        )
        with self._lock, self.conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM frames_fts JOIN frames f ON f.id = frames_fts.rowid"
                f" WHERE {' AND '.join(where)}",
                params,
            ).fetchone()[0]
            rows = conn.execute(sql, (*params, limit, offset)).fetchall()
            items = [dict(r) for r in rows]
            return total, items

    # ---- tracks / events ----

    def insert_track(self, *, ts: int, player: str, artist: str | None,
                     title: str, album: str | None, status: str | None) -> None:
        with self._lock, self.conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO tracks (ts, player, artist, title, album, status)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (ts, player, artist, title, album, status),
            )
            conn.commit()

    def list_tracks(self, start: int | None = None, end: int | None = None) -> list[dict]:
        self.query_count += 1
        where, params = "", []
        if start is not None:
            where += " WHERE ts >= ?"
            params.append(start)
        if end is not None:
            where += (" AND" if where else " WHERE") + " ts <= ?"
            params.append(end)
        with self._lock, self.conn() as conn:
            rows = conn.execute(
                f"SELECT ts, player, artist, title, album, status FROM tracks{where}"
                " ORDER BY ts",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def insert_event(self, *, ts: int, raw: str) -> None:
        with self._lock, self.conn() as conn:
            conn.execute("INSERT OR IGNORE INTO events (ts, raw) VALUES (?, ?)", (ts, raw))
            conn.commit()

    # ---- watch sessions ----

    def insert_watch_session(self, session: WatchSession) -> int:
        with self._lock, self.conn() as conn:
            cur = conn.execute(
                "INSERT INTO watch_sessions (player, media_title, media_source, media_id,"
                " ts_start, ts_end, pos_start, pos_end, length, ranges)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session.player, session.media_title, session.media_source, session.media_id,
                 session.ts_start, session.ts_end, session.pos_start, session.pos_end,
                 session.length, json.dumps(session.ranges)),
            )
            conn.commit()
            return cur.lastrowid

    def insert_live_session(self, player: str, media_title, media_source, media_id, *,
                            ts_start: int, pos_start: int, length: int,
                            ranges: list) -> int:
        """Open row for an in-progress session: live=1, ts_end=0, pos_end mirrors
        the starting position. `ranges` holds only the segments closed so far."""
        with self._lock, self.conn() as conn:
            cur = conn.execute(
                "INSERT INTO watch_sessions (player, media_title, media_source, media_id,"
                " ts_start, ts_end, pos_start, pos_end, length, ranges, live)"
                " VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, 1)",
                (player, media_title, media_source, media_id, ts_start,
                 pos_start, pos_start, length, json.dumps(ranges)),
            )
            conn.commit()
            return cur.lastrowid

    def update_live_session(self, row_id: int, *, ts_end: int, pos_end: int,
                            ranges: list) -> None:
        """Refresh an in-progress row (polls and follow lines); live rows only."""
        with self._lock, self.conn() as conn:
            conn.execute(
                "UPDATE watch_sessions SET ts_end = ?, pos_end = ?, ranges = ?"
                " WHERE id = ? AND live = 1",
                (ts_end, pos_end, json.dumps(ranges), row_id),
            )
            conn.commit()

    def update_live_media(self, row_id: int, *, media_source, media_id) -> None:
        """Attach CDP-resolved URL/video id to an open session's row (#36).

        Only live rows; the FTS update triggers keep search in sync."""
        with self._lock, self.conn() as conn:
            conn.execute(
                "UPDATE watch_sessions SET media_source = ?, media_id = ?"
                " WHERE id = ? AND live = 1",
                (media_source, media_id, row_id),
            )
            conn.commit()

    def finalize_live_session(self, row_id: int, *, ts_end: int, pos_end: int,
                              ranges: list) -> None:
        """Close an in-progress row in place: live=0 with the final values."""
        with self._lock, self.conn() as conn:
            conn.execute(
                "UPDATE watch_sessions SET live = 0, ts_end = ?, pos_end = ?, ranges = ?"
                " WHERE id = ?",
                (ts_end, pos_end, json.dumps(ranges), row_id),
            )
            conn.commit()

    def list_watch_sessions(self, *, player: str | None = None, start: int | None = None,
                            end: int | None = None, limit: int = 20,
                            offset: int = 0) -> tuple[int, list[dict]]:
        self.query_count += 1
        clauses, params = [], []
        if player is not None:
            clauses.append("player = ?")
            params.append(player)
        if start is not None:
            clauses.append("ts_start >= ?")
            params.append(start)
        if end is not None:
            clauses.append("ts_start <= ?")
            params.append(end)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self.conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM watch_sessions{where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT {', '.join(SESSION_COLS)} FROM watch_sessions{where}"
                " ORDER BY ts_start DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            items = [_session_item(r) for r in rows]
            return total, items

    def get_watch_session(self, session_id: int) -> dict | None:
        self.query_count += 1
        with self._lock, self.conn() as conn:
            row = conn.execute(
                f"SELECT {', '.join(SESSION_COLS)} FROM watch_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return _session_item(row) if row else None

    def search_watch_sessions(self, query: str, *, player: str | None = None,
                              start: int | None = None, end: int | None = None,
                              limit: int = 20, offset: int = 0,
                              order: str = "score") -> tuple[int, list[dict]]:
        """FTS5 over watch_sessions title/source — the #41 merged-search seam.

        bm25 weights: title 2.0, source 1.0 (titles are cleaner identifiers).
        `order="ts"` sorts by ts_start newest-first instead of by bm25 score
        (the #37 merged-search timeline). Raises sqlite3.OperationalError on an
        invalid FTS5 MATCH.
        """
        self.query_count += 1
        where = ["watch_sessions_fts MATCH ?"]
        params = [query]
        if player is not None:
            where.append("s.player = ?")
            params.append(player)
        if start is not None:
            where.append("s.ts_start >= ?")
            params.append(start)
        if end is not None:
            where.append("s.ts_start <= ?")
            params.append(end)
        order_by = "s.ts_start DESC" if order == "ts" else "score"
        sql = (
            "SELECT s.id, s.player, s.media_title, s.media_source, s.ts_start, s.ts_end,"
            " s.pos_start, s.pos_end, s.length, s.ranges,"
            " COALESCE(snippet(watch_sessions_fts, 0, '**', '**', ' … ', 14),"
            "          snippet(watch_sessions_fts, 1, '**', '**', ' … ', 14)) AS snippet,"
            " bm25(watch_sessions_fts, 2.0, 1.0) AS score"
            " FROM watch_sessions_fts JOIN watch_sessions s ON s.id = watch_sessions_fts.rowid"
            f" WHERE {' AND '.join(where)} ORDER BY {order_by}"
            " LIMIT ? OFFSET ?"
        )
        with self._lock, self.conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM watch_sessions_fts"
                " JOIN watch_sessions s ON s.id = watch_sessions_fts.rowid"
                f" WHERE {' AND '.join(where)}",
                params,
            ).fetchone()[0]
            rows = conn.execute(sql, (*params, limit, offset)).fetchall()
            return total, [_session_item(r) for r in rows]


def _session_item(row: sqlite3.Row) -> dict:
    item = dict(row)
    try:
        item["ranges"] = json.loads(item["ranges"]) if item["ranges"] else []
    except (TypeError, ValueError):
        item["ranges"] = []
    return item
