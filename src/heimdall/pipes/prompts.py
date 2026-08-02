"""Prompt templates + response_format JSON schemas for the pipes.

The system prompt tells the model the user's real activities and that
music/movies/YouTube are under-sampled so they must be inferred from titles
(the single-shot plain-pipe prompt proven in ticket #4).
"""

from __future__ import annotations

SYSTEM_PROMPT = (
    "You are Heimdall, a local screen-memory recap agent for a single user on Hyprland. "
    "You are given OCR'd window frames captured throughout the day. The user's real "
    "activities include: building projects, researching, applying to jobs/internships, "
    "watching YouTube, movies, listening to music, practicing DSA. "
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
            "Search the day's OCR'd screen frames by keyword. Returns up to "
            "`limit` ranked hits with timestamps and snippets."
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
    "Music/movies/YouTube have few or no window events, so infer those from window titles. "
    "You have access to the db_search tool: it searches the day's OCR'd window frames and "
    "returns ranked snippets with timestamps. Call it as many times as you need to gather "
    "evidence about what the user did today. When you have gathered enough, stop calling "
    "tools and answer with a single JSON object exactly of the shape "
    '{"date": "YYYY-MM-DD", "summary": string, "accomplishments": [string], '
    '"unfinished": [string], "standout": [string]} and no other text.'
)


def est_tokens(text: str) -> int:
    """Rough token estimate (~3.5 chars/token), used only for prompt budgeting."""
    return max(1, len(text) // 3.5)


def build_recap_prompt(frames: list[dict], day: str, budget_tokens: int = 6000) -> str:
    """Per-frame `ts | window_class | window_title` lines, titles primary.

    A short OCR snippet is appended per frame up to `budget_tokens`; all frames
    keep their title line (never truncate the frame list). Raises ValueError if
    even the title-only prompt exceeds the hard context budget.
    """
    frames = sorted(frames, key=lambda f: f["ts"])
    lines = []
    snippet_budget = budget_tokens
    for f in frames:
        line = f"{f['ts']} | {f['window_class']} | {f['window_title']}"
        ocr = (f.get("ocr_text") or "").strip().replace("\n", " ")
        if ocr and est_tokens(line) + est_tokens(ocr[:OCR_SNIPPET_CHARS]) < snippet_budget:
            line += f"  ocr: {ocr[:OCR_SNIPPET_CHARS]}"
            snippet_budget -= est_tokens(ocr[:OCR_SNIPPET_CHARS])
        lines.append(line)
    text = "Here are today's frames:\n\n" + "\n".join(lines)
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
