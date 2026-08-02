"""Span-based timing (secondary test seam, spec #8).

A span is a contiguous interval of time attributed to one window. Consecutive
frames delimit spans; the last frame's span runs to the end of the day.
Music timing comes from exact `tracks` play/pause spans; movies/YouTube come
from window-title/activewindow deltas; silent stretches are filled by
keepalive frames (their spans just belong to whatever window they captured).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Span:
    start_ms: int
    end_ms: int
    window_class: str
    window_title: str
    trigger: str

    @property
    def minutes(self) -> float:
        return (self.end_ms - self.start_ms) / 60_000


def compute_spans(frames: list[dict], end_ms: int) -> list[Span]:
    """Consecutive-frame deltas. `frames` need not be sorted; ts is UTC ms."""
    ordered = sorted(frames, key=lambda f: f["ts"])
    spans = []
    for i, f in enumerate(ordered):
        start = f["ts"]
        end = ordered[i + 1]["ts"] if i + 1 < len(ordered) else end_ms
        if end <= start:
            continue
        spans.append(Span(
            start_ms=start,
            end_ms=end,
            window_class=f.get("window_class") or "",
            window_title=f.get("window_title") or "",
            trigger=f.get("trigger") or "",
        ))
    return spans


def track_playing_ms(tracks: list[dict], start_ms: int, end_ms: int) -> int:
    """Exact playback time from MPRIS play/pause events, clipped to [start, end)."""
    ordered = sorted(tracks, key=lambda t: t["ts"])
    total = 0
    play_start: int | None = None
    for t in ordered:
        status = (t.get("status") or "").lower()
        if status == "playing" and play_start is None:
            play_start = max(t["ts"], start_ms)
        elif status == "paused" and play_start is not None:
            total += max(0, min(t["ts"], end_ms) - play_start)
            play_start = None
    if play_start is not None:
        total += max(0, end_ms - play_start)
    return total


def rules_minutes(spans: list[Span], rules: dict) -> tuple[dict[str, int], list[Span]]:
    """Split spans into rules-settled category minutes and the unclassified rest.

    `rules` maps window_class -> category (config `rules.window_class_category`).
    Returns (settled_minutes, unclassified_spans).
    """
    settled: dict[str, int] = {}
    unclassified: list[Span] = []
    for s in spans:
        cat = rules.get(s.window_class)
        if cat is not None:
            settled[cat] = settled.get(cat, 0) + max(0, s.end_ms - s.start_ms)
        else:
            unclassified.append(s)
    return settled, unclassified


def spans_to_table(spans: list[Span]) -> list[dict]:
    """Per-window rows for the LLM classification prompt (class | title | minutes)."""
    rows: dict[tuple[str, str], float] = {}
    for s in spans:
        key = (s.window_class, s.window_title)
        rows[key] = rows.get(key, 0.0) + s.minutes
    return [
        {"window_class": k[0], "window_title": k[1], "minutes": round(v)}
        for k, v in sorted(rows.items(), key=lambda kv: -kv[1])
    ]
