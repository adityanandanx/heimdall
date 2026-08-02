"""Time breakdown pipe: hybrid classification (rules settle, LLM classifies the rest).

Timing sources: Music = exact `tracks` play/pause spans; Movies/YouTube =
window-title/activewindow deltas; gaps = keepalive frames; remainder = Other.
"""

from __future__ import annotations

from pathlib import Path

from heimdall.capture.spans import compute_spans, rules_minutes, spans_to_table, track_playing_ms
from heimdall.config import Config
from heimdall.db import Database
from heimdall.observability import TraceGate
from heimdall.pipes.llm import LlmClient
from heimdall.pipes.parse import parse_breakdown
from heimdall.pipes.prompts import (
    BREAKDOWN_CATEGORIES,
    BREAKDOWN_SCHEMA,
    SYSTEM_PROMPT,
    build_breakdown_prompt,
)
from heimdall.pipes.render import render_breakdown
from heimdall.timeutil import day_bounds, day_range_iso, now_iso


def normalize_category(name: str) -> str:
    for cat in BREAKDOWN_CATEGORIES:
        if cat.lower() == name.strip().lower():
            return cat
    return "Other"


def assemble_minutes(settled: dict[str, int], music_ms: int, llm_categories: list[dict],
                     unclassified_ms: int) -> dict[str, int]:
    """Combine rules-settled, exact-music and LLM-classified minutes.

    Music is overridden by exact playback time when tracks exist; the LLM's
    category names outside the fixed vocabulary fold into Other; the residual
    of unclassified time the LLM did not account for lands in Other.
    """
    minutes = {cat: 0 for cat in BREAKDOWN_CATEGORIES}
    for cat, ms in settled.items():
        minutes[cat] = minutes.get(cat, 0) + round(ms / 60_000)
    if music_ms > 0:
        minutes["Music"] = round(music_ms / 60_000)
    assigned = 0
    for item in llm_categories:
        mins = max(0, int(item["minutes"]))
        minutes[normalize_category(item["category"])] += mins
        assigned += mins
    residual = unclassified_ms - assigned
    minutes["Other"] += max(0, round(residual / 60_000))
    return minutes


def run(*, day: str, db_path: str | Path, llm: LlmClient, gate: TraceGate,
        config: Config, output_dir: str | Path | None = None) -> dict:
    start_ms, end_ms = day_bounds(day)
    db = Database(db_path)
    frames = db.frames_in_range(start_ms, end_ms)
    tracks = db.list_tracks(start_ms, end_ms)

    spans = compute_spans(frames, end_ms)
    rules = config.window_class_category
    settled, unclassified = rules_minutes(spans, rules)
    music_ms = track_playing_ms(tracks, start_ms, end_ms)

    llm_categories: list[dict] = []
    if unclassified:
        table = spans_to_table(unclassified)
        prompt = build_breakdown_prompt(table, day)
        raw = llm.complete(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": prompt}],
            BREAKDOWN_SCHEMA,
        )
        llm_categories = parse_breakdown(raw)["categories"]

    unclassified_ms = sum(max(0, s.end_ms - s.start_ms) for s in unclassified)
    minutes = assemble_minutes(settled, music_ms, llm_categories, unclassified_ms)

    evidence = build_evidence(settled, music_ms, tracks, llm_categories)

    trace_url = gate.trace_url()
    markdown = render_breakdown(
        minutes, evidence,
        date=day,
        range_=day_range_iso(day),
        generated_at=now_iso(),
        frame_count=len(frames),
        trace_url=trace_url,
    )

    out_dir = Path(output_dir) if output_dir else Path(db_path).parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"time-breakdown-{day}.md"
    path.write_text(markdown, encoding="utf-8")
    return {
        "markdown": markdown,
        "output_path": str(path.relative_to(Path(db_path).parent)),
        "trace_url": trace_url,
        "frame_count": len(frames),
    }


def build_evidence(settled: dict[str, int], music_ms: int, tracks: list[dict],
                   llm_categories: list[dict]) -> dict[str, str]:
    evidence: dict[str, str] = {}
    if music_ms > 0:
        evidence["Music"] = f"exact playback spans from {len(tracks)} track events"
    elif "Music" in settled:
        evidence["Music"] = "window-class rule (music player frames)"
    for cat in ("Movies", "Building projects", "Researching", "Job applications", "YouTube", "DSA"):
        if cat in settled:
            evidence[cat] = "window-class rule (frame/title spans)"
    for item in llm_categories:
        evidence[normalize_category(item["category"])] = item.get("evidence") or "LLM-classified window spans"
    return evidence
