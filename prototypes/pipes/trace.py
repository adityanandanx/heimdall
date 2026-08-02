"""Local trace recorder for the pipe experiment. PROTOTYPE — wipe me.

Writes per-variant, into traces/<variant>/:
  run.jsonl      — event stream: step, payload, timing
  raw/*.txt      — raw artifacts: prompts, full model responses, tool results

Everything a human needs to manually verify the claims in compare.md.
"""

import json
import time
from pathlib import Path

TRACES = Path(__file__).parent / "traces"


class Trace:
    def __init__(self, name: str):
        self.name = name
        self.dir = TRACES / name
        self.raw_dir = self.dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []
        self.start = time.perf_counter()

    def event(self, step: str, **data) -> None:
        self.events.append({"t": round(time.perf_counter() - self.start, 3), "step": step, **data})

    def raw(self, label: str, text: str) -> None:
        (self.raw_dir / f"{label}.txt").write_text(text)

    def save(self) -> None:
        (self.dir / "run.jsonl").write_text(
            "\n".join(json.dumps(e) for e in self.events) + "\n"
        )
        print(f"  \x1b[2mtraces: {self.dir} ({len(self.events)} events)\x1b[0m")
