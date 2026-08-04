"""Day recap pipe: plain function (load -> prompt -> completion -> parse -> render -> write).

Days whose title-only prompt exceeds the hard context budget switch to the
documented agent path: a tool loop over the FTS5 `db_search` tool (spec #4),
never truncation.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from heimdall.db import Database
from heimdall.observability import TraceGate
from heimdall.pipes.llm import LlmClient
from heimdall.pipes.parse import parse_recap
from heimdall.pipes.prompts import (
    DB_SEARCH_TOOL,
    PromptOverBudget,
    RETRIEVAL_SYSTEM_PROMPT,
    RECAP_SCHEMA,
    SYSTEM_PROMPT,
    build_recap_prompt,
)
from heimdall.pipes.render import render_recap, write_markdown
from heimdall.timeutil import day_bounds, day_range_iso, now_iso

log = logging.getLogger("heimdall.pipes.recap")

MAX_AGENT_TURNS = 6
MAX_SEARCH_LIMIT = 25


def run(*, day: str, db_path: str | Path, llm: LlmClient, gate: TraceGate,
        output_dir: str | Path | None = None, config=None) -> dict:
    start_ms, end_ms = day_bounds(day)
    db = Database(db_path)
    frames = db.frames_in_range(start_ms, end_ms)
    _, sessions = db.list_watch_sessions(start=start_ms, end=end_ms, limit=100_000)

    try:
        recap = _one_shot(day, frames, sessions, llm, gate)
        mode = "single-shot"
    except PromptOverBudget:
        log.info("day %s over budget (%s frames): using FTS5 db_search tool loop", day, len(frames))
        recap = run_recap_agent(db=db, llm=llm, gate=gate,
                                start_ms=start_ms, end_ms=end_ms)
        mode = "agent"

    gate.metadata(db_queries=db.query_count)

    trace_url = gate.trace_url()
    markdown = render_recap(
        recap,
        date=day,
        range_=day_range_iso(day),
        generated_at=now_iso(),
        frame_count=len(frames),
        trace_url=trace_url,
    )

    output_path = write_markdown(markdown, f"day-recap-{day}.md", db_path, output_dir)
    return {
        "markdown": markdown,
        "output_path": output_path,
        "trace_url": trace_url,
        "frame_count": len(frames),
        "mode": mode,
    }


def _one_shot(day: str, frames: list[dict], sessions: list[dict], llm: LlmClient,
              gate: TraceGate) -> dict:
    prompt = build_recap_prompt(frames, day, sessions=sessions)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    raw = llm.complete(messages, RECAP_SCHEMA, gate=gate)
    with gate.span("parse-recap"):
        return parse_recap(raw)


def run_recap_agent(*, db: Database, llm: LlmClient, gate: TraceGate,
                    start_ms: int, end_ms: int) -> dict:
    """Tool-first retrieval: the model gathers evidence with `db_search` calls
    against FTS5 and finishes with a single JSON recap (#4)."""
    messages = [{"role": "system", "content": RETRIEVAL_SYSTEM_PROMPT}]
    for _ in range(MAX_AGENT_TURNS):
        raw = llm.complete_tools(messages, [DB_SEARCH_TOOL], gate=gate)
        tool_calls = raw.get("tool_calls")
        if not tool_calls:
            with gate.span("parse-recap"):
                return parse_recap(raw.get("content") or "")
        messages.append(raw)
        for call in tool_calls:
            try:
                result = _exec_db_search(db, _tool_args(call), start_ms, end_ms)
            except PromptOverBudget as exc:
                result = f"error: {exc}"
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id") or "",
                "content": result,
            })
    # loop exhausted without a final answer: force a recap completion over the
    # evidence gathered so far (still no truncation, no crash)
    raw = llm.complete(messages, RECAP_SCHEMA, gate=gate)
    with gate.span("parse-recap"):
        return parse_recap(raw)


def _tool_args(call: dict) -> dict:
    fn = call.get("function") or {}
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError as exc:
        raise PromptOverBudget(f"malformed tool arguments: {exc}") from exc
    if not isinstance(args, dict):
        raise PromptOverBudget(f"tool arguments must be a JSON object, got {type(args).__name__}")
    return args


def _exec_db_search(db: Database, args: dict, start_ms: int, end_ms: int) -> str:
    """Execute a `db_search` call; return a token-tolerant result string that is
    safe to hand back to the model (never raises on bad input)."""
    query = str(args.get("query") or "")
    if not query:
        return "error: `query` is required"
    try:
        limit = max(1, min(int(args.get("limit") or 10), MAX_SEARCH_LIMIT))
    except (TypeError, ValueError):
        limit = 10
    window_class = args.get("window_class")
    try:
        total, hits = db.search(query, window_class=window_class,
                                start=start_ms, end=end_ms, limit=limit)
    except sqlite3.OperationalError as exc:
        return f"error: invalid FTS5 query: {exc}"
    if total == 0:
        return "no results"
    lines = [f"hits: {total} (showing {len(hits)})"]
    for h in hits:
        lines.append(
            f"- ts={h['ts']} class={h['window_class'] or ''} title={h['window_title'] or ''} "
            f"snippet={h['snippet']}"
        )
    return "\n".join(lines)
