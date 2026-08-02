"""Shared, portable pipe logic — the only bit that would lift into real code.

Pure functions only: no I/O, no HTTP, no sqlite. Each pipe variant does its own
I/O and calls into these.

PROTOTYPE — wipe me.
"""

import json

BASE_URL = "http://localhost:8080/v1"
MODEL = "/home/aditya/.cache/huggingface/hub/models--google--gemma-4-E2B-it-qat-q4_0-gguf/snapshots/675cff42a74c774d6cb76f76d8eacb49b48c9b93/gemma-4-E2B_q4_0-it.gguf"

SYSTEM_PROMPT = """You are Heimdall, a local screen-memory recap agent for a single user on Hyprland.
You are given OCR'd window frames captured throughout the day. Produce a structured
day recap in JSON. The user's real activities include: building projects, researching,
applying to jobs/internships, watching YouTube, movies, listening to music, practicing DSA.
Windows like music players, movies and YouTube have few or no events, so infer those from
window titles. Group everything into a small set of categories with rough minutes each."""

# JSON Schema passed as response_format — both pipes must return exactly this shape.
RECAP_SCHEMA = {
    "type": "json_object",
    "schema": {
        "type": "object",
        "properties": {
            "date": {"type": "string"},
            "summary": {"type": "string"},
            "categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "minutes": {"type": "integer"},
                        "detail": {"type": "string"},
                    },
                    "required": ["name", "minutes", "detail"],
                },
            },
            "highlights": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["date", "summary", "categories", "highlights"],
    },
}


def build_prompt(frames: list[dict]) -> str:
    """One frame per line: ts | window class | title."""
    lines = []
    for f in sorted(frames, key=lambda x: x["ts"]):
        lines.append(f'{f["ts"]} | {f["cls"]} | {f["title"]}')
    return "Here are today's frames:\n\n" + "\n".join(lines)


def build_tool_prompt(frames: list[dict]) -> str:
    """For the agent variant: the frames are NOT inlined; the model is told to query."""
    count = len(frames)
    first, last = frames[0]["ts"], frames[-1]["ts"]
    return (
        f"Summarize the user's day between {first} and {last} ({count} frames captured). "
        "You MUST use the db_search tool to query the frames before answering. "
        "Call it at least once — suggest 3-4 substring queries (e.g. 'youtube', 'movie', "
        "'leetcode', 'linkedin') to cover the activities. You may call it more than once. "
        "Do not answer until you have called the tool. "
        "Answer with a single JSON object and no other text, with EXACTLY these keys: "
        "date (string), summary (string), categories (array of {name, minutes, detail}), "
        "highlights (array of strings)."
    )


def parse_recap(content: str) -> dict:
    """Strict-ish: strip code fences, find the first JSON object, require schema fields."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip("` \n")
    obj = json.loads(text)
    if isinstance(obj, dict) and all(k not in obj for k in ("date", "summary", "categories", "highlights")):
        # tolerate a single top-level wrapper key (e.g. {"day_recap": {...}})
        wrapped = [v for v in obj.values() if isinstance(v, dict)]
        if len(obj) == 1 and wrapped:
            obj = wrapped[0]
    for k in ("date", "summary", "categories", "highlights"):
        if k not in obj:
            raise ValueError(f"missing key {k!r}")
    return obj


def render_markdown(recap: dict) -> str:
    c = recap["categories"]
    total = sum(x.get("minutes", 0) for x in c)
    rows = "\n".join(
        f"- **{x['name']}** — {x['minutes']} min\n  {x['detail']}" for x in c
    )
    bullets = "\n".join(f"- {h}" for h in recap["highlights"])
    return f"""# Day recap — {recap['date']}

{recap['summary']}

## Categories ({total} min tracked)

{rows}

## Highlights

{bullets}
"""
