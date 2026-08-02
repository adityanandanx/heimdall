"""Day recap pipe: plain function (load -> prompt -> completion -> parse -> render -> write)."""

from __future__ import annotations

from pathlib import Path

from heimdall.db import Database
from heimdall.observability import TraceGate
from heimdall.pipes.llm import LlmClient
from heimdall.pipes.parse import parse_recap
from heimdall.pipes.prompts import RECAP_SCHEMA, SYSTEM_PROMPT, build_recap_prompt
from heimdall.pipes.render import render_recap
from heimdall.timeutil import day_bounds, day_range_iso, now_iso


def run(*, day: str, db_path: str | Path, llm: LlmClient, gate: TraceGate,
        output_dir: str | Path | None = None, config=None) -> dict:
    start_ms, end_ms = day_bounds(day)
    db = Database(db_path)
    frames = db.frames_in_range(start_ms, end_ms)

    prompt = build_recap_prompt(frames, day)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    raw = llm.complete(messages, RECAP_SCHEMA)
    recap = parse_recap(raw)

    trace_url = gate.trace_url()
    markdown = render_recap(
        recap,
        date=day,
        range_=day_range_iso(day),
        generated_at=now_iso(),
        frame_count=len(frames),
        trace_url=trace_url,
    )

    out_dir = Path(output_dir) if output_dir else Path(db_path).parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"day-recap-{day}.md"
    path.write_text(markdown, encoding="utf-8")
    return {
        "markdown": markdown,
        "output_path": str(path.relative_to(Path(db_path).parent)),
        "trace_url": trace_url,
        "frame_count": len(frames),
    }
