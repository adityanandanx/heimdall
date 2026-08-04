"""Prompt templates + response_format JSON schemas for the pipes.

The system prompt tells the model the user's real activities and that
music/movies/YouTube are under-sampled so they must be inferred from titles
(the single-shot plain-pipe prompt proven in ticket #4).
"""

from __future__ import annotations

SYSTEM_PROMPT = (
    "You are Heimdall, a local screen-memory recap agent for a single user on Hyprland. "
    "You are given window frames captured throughout the day — exact a11y tree text where "
    "a window exposes it, OCR otherwise — plus media watch-sessions (YouTube/Movies) with "
    "their watched range and transcript. The user's real activities include: building "
    "projects, researching, applying to jobs/internships, watching YouTube, movies, "
    "listening to music, practicing DSA. "
    "Windows like music players, movies and YouTube have few or no window events, so "
    "infer those from window titles. Group everything into a small set of categories "
    "with rough minutes each. Answer with a single JSON object and no other text."
)

RECAP_SCHEMA = {
    "type": "json_object",
    "schema": {
        "type": "object",
        "properties": {
            "date": {"type": "string"},
            "summary": {"type": "string"},
            "accomplishments": {"type": "array", "items": {"type": "string"}},
            "unfinished": {"type": "array", "items": {"type": "string"}},
            "standout": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["date", "summary", "accomplishments", "unfinished", "standout"],
    },
}

BREAKDOWN_CATEGORIES = (
    "Building projects",
    "Researching",
    "Job applications",
    "YouTube",
    "Movies",
    "Music",
    "DSA",
    "Other",
)

BREAKDOWN_SCHEMA = {
    "type": "json_object",
    "schema": {
        "type": "object",
        "properties": {
            "categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "minutes": {"type": "integer"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["category", "minutes", "evidence"],
                },
            }
        },
        "required": ["categories"],
    },
}

OCR_SNIPPET_CHARS = 200
HARD_CONTEXT_TOKENS = 7800


class PromptOverBudget(ValueError):
    """Raised when even the title-only recap prompt exceeds the hard context
    budget; the pipe switches to the FTS5 db_search tool loop instead."""


DB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "db_search",
        "description": (
            "Search the day's screen memory — window frames (a11y/OCR text) and "
            "media watch-session transcripts — by keyword. Returns up to `limit` "
            "ranked hits with timestamps and snippets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "FTS5 keyword/phrase, e.g. 'leetcode' or 'youtube'"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                "window_class": {"type": "string",
                                 "description": "Restrict to a window class, e.g. 'firefox'"},
            },
            "required": ["query"],
        },
    },
}

RETRIEVAL_SYSTEM_PROMPT = (
    "You are Heimdall, a local screen-memory recap agent for a single user on Hyprland. "
    "The user's real activities include: building projects, researching, applying to "
    "jobs/internships, watching YouTube, movies, listening to music, practicing DSA. "
    "Music/movies/YouTube have few or no window events, so infer those from window titles "
    "and media watch-session transcripts. "
    "You have access to the db_search tool: it searches the day's window frames (a11y/OCR "
    "text) and media watch-session transcripts, returning ranked snippets with timestamps. "
    "Call it as many times as you need to gather "
    "evidence about what the user did today. When you have gathered enough, stop calling "
    "tools and answer with a single JSON object exactly of the shape "
    '{"date": "YYYY-MM-DD", "summary": string, "accomplishments": [string], '
    '"unfinished": [string], "standout": [string]} and no other text.'
)


def est_tokens(text: str) -> int:
    """Rough token estimate (~3.5 chars/token), used only for prompt budgeting."""
    return max(1, len(text) // 3.5)


def _fmt_video_us(us: int) -> str:
    """Video-time microseconds as 'H:MM:SS' (hours dropped when zero)."""
    total_s = us // 1_000_000
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _media_session_lines(sessions: list[dict]) -> list[str]:
    """One prompt line per closed media session (#41): title + watched range +
    a short transcript snippet. Media windows produce no OCR/a11y text, so the
    session line is their only content in the recap."""
    lines = []
    for s in sorted(sessions, key=lambda s: s.get("ts_start") or 0):
        if s.get("live") or s.get("ts_end") is None:
            continue
        line = f"{s['ts_start']} | media: {s.get('media_title') or 'untitled'}"
        if s.get("pos_start") is not None and s.get("pos_end") is not None:
            line += f" | watched {_fmt_video_us(s['pos_start'])}-{_fmt_video_us(s['pos_end'])}"
        snippet = (s.get("transcript") or "").strip().replace("\n", " ")
        if snippet:
            line += f" | transcript: {snippet[:OCR_SNIPPET_CHARS]}"
        lines.append(line)
    return lines


def build_recap_prompt(frames: list[dict], day: str, *, sessions: list[dict] | None = None,
                       budget_tokens: int = 6000) -> str:
    """Per-frame `ts | window_class | window_title` lines, titles primary.

    Each frame's line carries the winner text snippet — `a11y:` when the tree
    won, else `ocr:` — up to `budget_tokens`; all frames keep their title line
    (never truncate the frame list). Frames whose window is a media watch-session
    are dropped in favour of a session line (title + watched range + transcript
    snippet). Raises ValueError if even the title-only prompt exceeds the hard
    context budget.
    """
    frames = sorted(frames, key=lambda f: f["ts"])
    sessions = sessions or []
    media_titles = {s.get("media_title") for s in sessions if s.get("media_title")}
    lines = []
    snippet_budget = budget_tokens
    for f in frames:
        if (f.get("window_title") or "") in media_titles:
            continue
        line = f"{f['ts']} | {f['window_class']} | {f['window_title']}"
        winner = (f.get("a11y_text") or "").strip().replace("\n", " ")
        label = "a11y"
        if not winner:
            winner = (f.get("ocr_text") or "").strip().replace("\n", " ")
            label = "ocr"
        if winner and est_tokens(line) + est_tokens(winner[:OCR_SNIPPET_CHARS]) < snippet_budget:
            line += f"  {label}: {winner[:OCR_SNIPPET_CHARS]}"
            snippet_budget -= est_tokens(winner[:OCR_SNIPPET_CHARS])
        lines.append(line)
    text = "Here are today's frames:\n\n" + "\n".join(lines)
    media_lines = _media_session_lines(sessions)
    if media_lines:
        text += ("\n\nHere are today's media watch-sessions (these windows produce "
                 "no OCR/a11y text):\n\n" + "\n".join(media_lines))
    if est_tokens(text) > HARD_CONTEXT_TOKENS:
        raise PromptOverBudget(
            f"day {day} has {len(frames)} frames: even the title-only prompt exceeds the "
            "model context. Use the documented agent/retrieval path (tool loop over FTS5), "
            "never truncation."
        )
    return text


def build_breakdown_prompt(spans: list[dict], day: str) -> str:
    """Per-window span table (`class | title | minutes`) for the LLM to classify."""
    rows = "\n".join(
        f"{s['window_class']} | {s['window_title']} | {round(s['minutes'])} min"
        for s in spans
    )
    cats = ", ".join(BREAKDOWN_CATEGORIES)
    return (
        f"Here is a per-window span table for {day} ({len(spans)} spans). "
        f"Assign every span to exactly one of these categories: {cats}. "
        "Minutes must match the span table.\n\n" + rows
    )
