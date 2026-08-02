"""Plain-function pipe: direct sqlite load -> httpx call -> markdown.

PROTOTYPE — wipe me. Variant A of ticket #4.
"""

import json
import time
from pathlib import Path

import httpx
from langfuse import observe

from core import BASE_URL, MODEL, RECAP_SCHEMA, SYSTEM_PROMPT, build_prompt, parse_recap, render_markdown
from lf import finish, trace_url
from scratch import load_frames
from trace import Trace

OUT = Path(__file__).parent / "out"


@observe(name="llm-completion", as_type="generation")
def _complete(payload: dict) -> dict:
    with httpx.Client(timeout=300) as client:
        r = client.post(f"{BASE_URL}/chat/completions", json=payload)
        r.raise_for_status()
    return r.json()


@observe(name="pipe-plain")
def run() -> dict:
    tr = Trace("plain")
    print("\x1b[1m[1/3] load\x1b[0m  direct sqlite: load_frames()")
    t0 = time.perf_counter()
    frames = load_frames()
    print(f"  loaded {len(frames)} frames in {time.perf_counter()-t0:.3f}s")
    tr.event("load", frames=len(frames))

    print("\x1b[1m[2/3] summarize\x1b[0m  one httpx POST, response_format=json")
    prompt = build_prompt(frames)
    tr.raw("prompt", prompt)
    t0 = time.perf_counter()
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "stream": False,
        "response_format": RECAP_SCHEMA,
    }
    data = _complete(payload)
    raw = data["choices"][0]["message"]["content"]
    dt = time.perf_counter() - t0
    print(f"  LLM round-trip {dt:.1f}s, {len(raw)} chars raw content")

    tr.raw("request", json.dumps(payload, indent=2))
    tr.raw("response", raw)
    tr.event("summarize", llm_secs=round(dt, 1), raw_chars=len(raw))

    recap = parse_recap(raw)
    print(f"  parsed recap: date={recap['date']}, {len(recap['categories'])} categories")
    tr.event("parse", categories=len(recap["categories"]))

    print("\x1b[1m[3/3] write\x1b[0m  render markdown")
    md = render_markdown(recap)
    OUT.mkdir(exist_ok=True)
    path = OUT / "plain.md"
    path.write_text(md)
    print(f"  wrote {path} ({len(md)} chars)")
    tr.raw("markdown", md)
    tr.event("write", path=str(path), chars=len(md))
    tr.save()
    url = trace_url()
    print(f"  \x1b[36mtrace: {url}\x1b[0m")
    return {"variant": "plain", "frames": len(frames), "llm_secs": round(dt, 1), "raw": raw, "recap": recap}


if __name__ == "__main__":
    from scratch import seed

    seed()
    try:
        print(json.dumps(run(), indent=2, default=str))
    finally:
        finish()
