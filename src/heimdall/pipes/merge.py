"""Deterministic multi-day breakdown merge (no extra LLM pass, #9).

Reads the last N per-day time-breakdown files, sums minutes per category and
renders a days x categories table + totals + best day per category.
"""

from __future__ import annotations

import re
from pathlib import Path

from heimdall.pipes.render import render_merge
from heimdall.timeutil import now_iso

_TABLE_ROW = re.compile(r"^\|\s*([A-Za-z][^|]*?)\s*\|\s*(\d+)\s*\|$")


def parse_breakdown_table(markdown: str) -> dict[str, int]:
    """Extract {category: minutes} from a rendered breakdown file.

    Scans for the `| Category | Minutes |` header, then collects `| Cat | N |`
    rows until a non-row line.
    """
    lines = markdown.splitlines()
    minutes: dict[str, int] = {}
    in_table = False
    for line in lines:
        s = line.strip()
        if not in_table:
            if s == "| Category | Minutes |":
                in_table = True
            continue
        if not s.startswith("|"):
            break
        m = _TABLE_ROW.match(s)
        if m:
            minutes[m.group(1).strip()] = int(m.group(2))
    return minutes


def day_files(output_dir: Path, days: int) -> list[Path]:
    """The `days` most recent time-breakdown-YYYY-MM-DD.md files, ascending."""
    files = sorted(output_dir.glob("time-breakdown-????-??-??.md"))
    return files[-days:]


def _best_day(per_day: dict[str, dict[str, int]], cat: str) -> str:
    best_day, best_val = "", -1
    for day, minutes in per_day.items():
        if minutes.get(cat, 0) > best_val:
            best_day, best_val = day, minutes.get(cat, 0)
    return f"{best_day} ({best_val})" if best_day else ""


def merge(output_dir: Path, days: int) -> dict:
    """Merge the last `days` breakdown files. Returns the render payload + markdown."""
    files = day_files(output_dir, days)
    if not files:
        raise FileNotFoundError("no time-breakdown files found to merge")
    per_day: dict[str, dict[str, int]] = {}
    for path in files:
        day = "-".join(path.stem.rsplit("-", 3)[-3:])
        per_day[day] = parse_breakdown_table(path.read_text(encoding="utf-8"))
    cats: list[str] = []
    for m in per_day.values():
        for c in m:
            if c not in cats:
                cats.append(c)
    totals = {c: sum(m.get(c, 0) for m in per_day.values()) for c in cats}
    best_day = {c: _best_day(per_day, c) for c in cats}
    end_day = max(per_day)
    start_day = min(per_day)
    markdown = render_merge(
        totals, per_day, best_day,
        end_day=end_day,
        days=days,  # the requested N, not len(per_day): filename is {endday}-{N}d.md
        range_=f"{start_day} - {end_day}",
        generated_at=now_iso(),
    )
    return {"markdown": markdown, "end_day": end_day, "days": days}
