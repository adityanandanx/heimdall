"""Shared pipe runner: load -> prompt -> completion -> parse -> render -> write.

Serves both `POST /pipes/run/{name}` and APScheduler's nightly runs. Tracing is
gated by the observability TraceGate (no-op by default).
"""

from __future__ import annotations

from time import perf_counter
from pathlib import Path

from heimdall.config import Config
from heimdall.observability import TraceGate
from heimdall.pipes.breakdown import run as run_breakdown
from heimdall.pipes.llm import LlmClient
from heimdall.pipes.recap import run as run_recap
from heimdall.timeutil import now_iso

PIPES: dict[str, object] = {
    "day-recap": run_recap,
    "time-breakdown": run_breakdown,
}


class UnknownPipeError(KeyError):
    pass


def registered_pipes() -> list[str]:
    return list(PIPES.keys())


def run_pipe(name: str, *, day: str, config: Config, db_path: str | Path,
             llm: LlmClient, gate: TraceGate | None = None) -> dict:
    if name not in PIPES:
        raise UnknownPipeError(name)
    gate = gate or TraceGate(config.observability.enabled)
    fn = gate.decorate(f"pipe-{name}")(PIPES[name])
    t0 = perf_counter()
    try:
        result = fn(day=day, db_path=db_path, llm=llm, gate=gate, config=config)
    finally:
        gate.flush()
    return {
        "pipe": name,
        "ts": now_iso(),
        "run_ms": round((perf_counter() - t0) * 1000),
        "output_markdown": result["markdown"],
        "output_path": result["output_path"],
        "trace_url": result["trace_url"],
        "frame_count": result["frame_count"],
    }
