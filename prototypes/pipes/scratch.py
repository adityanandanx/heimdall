"""Scratch frame source — PROTOTYPE, wipe me.

A tiny SQLite DB mirroring the planned frames table, seeded with one day of
realistic frames for the user's activities (IDE work, research, YouTube,
DSA practice, job applications, music).

Provides both access patterns the ticket compares:
- load_frames()  — direct SQLite query (the "plain" way)
- db_search()    — a tool for the agent variant (the LangGraph way)
"""

import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "scratch_pipes.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS frames (
    ts TEXT NOT NULL,
    monitor INTEGER NOT NULL,
    cls TEXT NOT NULL,
    title TEXT NOT NULL
);
"""

# ts | monitor | class | title
SEED = [
    ("2026-08-02 08:12", 0, "kitty", "zsh — htop"),
    ("2026-08-02 08:15", 0, "code", "src/heimdall/capture.py — heimdall (workspace)"),
    ("2026-08-02 08:40", 0, "kitty", "cargo build — heimdall"),
    ("2026-08-02 09:02", 0, "code", "capture.py — event loop: debounce & throttle"),
    ("2026-08-02 09:14", 1, "firefox", "LangGraph docs — checkpointers"),
    ("2026-08-02 09:38", 1, "firefox", "LangSmith docs — tracing"),
    ("2026-08-02 10:05", 1, "firefox", "youtube.com/watch?v=dQw4w9WgXcQ"),
    ("2026-08-02 10:22", 1, "firefox", "youtube.com/watch?v=— system design deep dive"),
    ("2026-08-02 10:55", 0, "code", "leetcode.com/problems/two-sum — solution.py"),
    ("2026-08-02 11:20", 0, "firefox", "leetcode.com/problems/lru-cache"),
    ("2026-08-02 11:48", 0, "code", "dsa/arrays.py — NeetCode 150"),
    ("2026-08-02 12:15", 1, "firefox", "linkedin.com/jobs — staff engineer roles"),
    ("2026-08-02 12:40", 1, "firefox", "wellfound.com/startups — apply"),
    ("2026-08-02 13:05", 1, "firefox", "youtube.com/watch?v=— lofi beats to study to"),
    ("2026-08-02 13:30", 1, "spotify", "— music"),
    ("2026-08-02 14:10", 0, "code", "capture.py — tesseract OCR pipeline"),
    ("2026-08-02 14:45", 1, "firefox", "docs.rs — sqlite fts5 syntax"),
    ("2026-08-02 15:20", 0, "kitty", "uv run pytest — capture tests"),
    ("2026-08-02 15:55", 1, "firefox", "arxiv.org — local LLM RAG survey"),
    ("2026-08-02 16:30", 0, "code", "heimdall — FastAPI routes"),
]


def seed() -> None:
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    con.execute("DELETE FROM frames")
    con.executemany(
        "INSERT INTO frames (ts, monitor, cls, title) VALUES (?,?,?,?)",
        [(ts, m, c, t) for ts, m, c, t in SEED],
    )
    con.commit()
    con.close()
    print(f"[scratch] seeded {len(SEED)} frames -> {DB.name} (PROTOTYPE, wipe me)")


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(DB)


def load_frames() -> list[dict]:
    con = _conn()
    rows = con.execute("SELECT ts, cls, title FROM frames ORDER BY ts").fetchall()
    con.close()
    return [{"ts": r[0], "cls": r[1], "title": r[2]} for r in rows]


def db_search(kind: str = "all", q: str = "") -> str:
    """Tool for the agent variant. kind: all|youtube|code|research|jobs|dsa.

    Token-tolerant match: split the query into tokens (non-alphanumeric
    boundaries) and match a frame if ANY token is a case-insensitive substring
    of its class or title. Naive whole-phrase LIKE made the 2B model's
    vocabulary-phrase queries (e.g. "watching youtube") return nothing even
    though the frames contain "youtube.com/...".
    """
    con = _conn()
    sql = "SELECT ts, cls, title FROM frames"
    params: tuple = ()
    if q:
        tokens = [t for t in __import__("re").split(r"[^a-z0-9]+", q.lower()) if t]
        if tokens:
            conds = " OR ".join(["title LIKE ? OR cls LIKE ?"] * len(tokens))
            sql += f" WHERE {conds}"
            params = tuple(t for tok in tokens for t in (f"%{tok}%", f"%{tok}%"))
    sql += " ORDER BY ts"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return "\n".join(f"{r[0]} | {r[1]} | {r[2]}" for r in rows) or "(no matches)"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "db_search",
            "description": "Query captured OCR frames by substring over window class or title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "substring to match (e.g. 'youtube', 'code')"}
                },
                "required": ["q"],
            },
        },
    }
]
