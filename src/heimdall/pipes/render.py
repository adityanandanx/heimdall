"""Markdown + front-matter rendering for pipe outputs (secondary test seam).

The single-day breakdown table (`| Category | Minutes |`) is the canonical
format the deterministic multi-day merge parses back out of day files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

BREAKDOWN_TABLE_HEADER = "| Category | Minutes |"
FOOTNOTE = "_Movie and music time derives from playback/title spans, not per-frame captures._"


def write_markdown(markdown: str, filename: str, db_path: str | Path,
                   output_dir: str | Path | None = None) -> str:
    """Render payload -> disk, returning the path relative to the data dir.

    Shared by the pipes so the write+mkdir+relative-path dance lives in one place.
    """
    out_dir = Path(output_dir) if output_dir else Path(db_path).parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(markdown, encoding="utf-8")
    return str(path.relative_to(Path(db_path).parent))


def _yaml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    unsafe = (
        s == ""
        or s != s.strip()
        or s[0] in "!&*{}[],#|>%@`'\""
        or "#" in s
        or ":" in s
    )
    return f'"{s}"' if unsafe else s


def front_matter(fields: dict) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value is None:
            continue
        lines.append(f"{key}: {_yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines)


def _bullets(items: Iterable[str]) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "_none_"


def render_recap(recap: dict, *, date: str, range_: str, generated_at: str,
                 frame_count: int, trace_url: str = "") -> str:
    fm = front_matter({
        "title": "Day recap",
        "date": date,
        "range": range_,
        "generated_at": generated_at,
        "frame_count": frame_count,
        "trace_url": trace_url,
    })
    return f"""{fm}

# Day recap — {date}

**Summary:** {recap['summary']}

## What I did

{_bullets(recap['accomplishments'])}

## Unfinished / to pick up

{_bullets(recap['unfinished'])}

## Standout

{_bullets(recap['standout'])}
"""


def render_breakdown_table(minutes: dict[str, int]) -> str:
    rows = [BREAKDOWN_TABLE_HEADER, "|---|---:|"]
    for cat in minutes:
        rows.append(f"| {cat} | {minutes[cat]} |")
    return "\n".join(rows)


def render_breakdown(minutes: dict[str, int], evidence: dict[str, str], *, date: str,
                     range_: str, generated_at: str, frame_count: int,
                     trace_url: str = "") -> str:
    fm = front_matter({
        "title": "Time breakdown",
        "date": date,
        "range": range_,
        "generated_at": generated_at,
        "frame_count": frame_count,
        "trace_url": trace_url,
    })
    total = sum(minutes.values())
    ev_rows = "\n".join(
        f"- **{cat}** — {minutes.get(cat, 0)} min: {evidence[cat]}"
        for cat in minutes if cat in evidence and evidence[cat]
    )
    return f"""{fm}

# Time breakdown — {date}

## Time by category

{render_breakdown_table(minutes)}

**Total:** {total} minutes

{FOOTNOTE}

## Evidence

{ev_rows if ev_rows else "_none_"}
"""


def render_merge(totals: dict[str, int], per_day: dict[str, dict[str, int]],
                 best_day: dict[str, str], *, end_day: str, days: int,
                 range_: str, generated_at: str) -> str:
    fm = front_matter({
        "title": f"Time breakdown ({days} days)",
        "date": end_day,
        "range": range_,
        "generated_at": generated_at,
        "days": days,
    })
    day_list = list(per_day.keys())
    total_row = ["| Category | Total (min) | Best day |", "|---|---|---|"]
    for cat in totals:
        bd = best_day.get(cat, "")
        total_row.append(f"| {cat} | {totals[cat]} | {bd} |")
    header = ["| Category | " + " | ".join(day_list) + " | Total |",
              "|" + "---|" * (len(day_list) + 2)]
    rows = []
    for cat in totals:
        cells = [str(per_day[d].get(cat, 0)) for d in day_list]
        rows.append(f"| {cat} | " + " | ".join(cells) + f" | {totals[cat]} |")
    grand = sum(totals.values())
    return f"""{fm}

# Time breakdown — {end_day} ({days} days)

## Totals

{chr(10).join(total_row)}

## Per day

{chr(10).join(header + rows)}

**Grand total:** {grand} minutes
"""
