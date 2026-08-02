"""heimdall CLI — every command is a thin HTTP client to the API (:3030).

`serve` is the only starter. `--json` is an output flag, not a config override.
Multi-day breakdown merges day-files locally (deterministic, no extra LLM pass).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

import click
import httpx
import typer

from heimdall.api.app import create_app
from heimdall.config import Config, load_config
from heimdall.pipes.merge import merge as merge_days
from heimdall.timeutil import parse_day, today_str

app = typer.Typer(help="heimdall — local screen memory", no_args_is_help=True)

_cfg: Config = load_config()
_client_factory: Callable[[Config, object | None], object] | None = None


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        super().__init__(detail)


class ApiClient:
    """Minimal JSON HTTP client for the heimdall API."""

    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.Client(base_url=base_url, timeout=300, transport=transport)

    def _check(self, r: httpx.Response) -> dict:
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise ApiError(r.status_code, str(detail))
        return r.json()

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._check(self._client.get(path, params=params))

    def post(self, path: str, params: dict | None = None) -> dict:
        return self._check(self._client.post(path, params=params))

    def close(self) -> None:
        self._client.close()


def _client(cfg: Config) -> ApiClient:
    if _client_factory is not None:
        return _client_factory(cfg, None)
    base = cfg.api.bind
    if base in ("0.0.0.0", "::"):
        base = "127.0.0.1"
    return ApiClient(f"http://{base}:{cfg.api.port}")


@app.callback()
def _callback(config_path: str = typer.Option(None, "--config", help="path to config.yaml")):
    global _cfg
    _cfg = load_config(config_path)


def _serve(cfg: Config) -> None:
    import uvicorn

    server = create_app(cfg, start_scheduler=True)
    uvicorn.run(server, host=cfg.api.bind, port=cfg.api.port, log_level="info")


@app.command("serve")
def serve() -> None:
    """Start the API + scheduler in the foreground."""
    _serve(_cfg)


@app.command("search")
def search(
    q: str,
    window_class: str = typer.Option(None, "--window-class"),
    start: str = typer.Option(None, "--start"),
    end: str = typer.Option(None, "--end"),
    limit: int = typer.Option(10, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Full-text search over OCR + window titles."""
    data = _client(_cfg).get("/search", {
        "q": q, "window_class": window_class, "start": start, "end": end,
        "limit": limit, "offset": offset,
    })
    if json_output:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    for item in data["items"]:
        print(f"{item['ts']} | {item['window_class']} | {item['window_title']}")
        print(f"  {item['snippet']}  (score {item['score']:.3f})")
    print(f"{data['total']} result(s)")


@app.command("recap")
def recap(day: str = typer.Argument("today")) -> None:
    """Run the day recap pipe for a day (today|yesterday|YYYY-MM-DD)."""
    _run_and_print("day-recap", day)


@app.command("run")
def run(pipe: str, day: str = typer.Option("today", "--day")) -> None:
    """Run any registered pipe for a day."""
    _run_and_print(pipe, day)


def _run_and_print(pipe: str, day: str, json_output: bool = False) -> dict:
    result = _client(_cfg).post(f"/pipes/run/{pipe}", {"day": parse_day(day)})
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['pipe']} ({day}): wrote {result['output_path']} in {result['run_ms']}ms")
        if result["trace_url"]:
            print(f"trace: {result['trace_url']}")
    return result


@app.command("breakdown")
def breakdown(
    day: str = typer.Argument("today"),
    days: int = typer.Option(1, "--days", min=1),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Time breakdown for a day, or a deterministic merge of the last N days."""
    resolved = parse_day(day)
    client = _client(_cfg)
    if days == 1:
        _run_and_print("time-breakdown", resolved, json_output)
        return
    out = _cfg.data_path / "output"
    out.mkdir(parents=True, exist_ok=True)
    for i in range(days - 1, -1, -1):
        d = _shift(resolved, i)
        path = out / f"time-breakdown-{d}.md"
        if not path.exists():
            client.post("/pipes/run/time-breakdown", {"day": d})
    merged = merge_days(out, days)
    out_path = out / f"time-breakdown-{merged['end_day']}-{merged['days']}d.md"
    out_path.write_text(merged["markdown"], encoding="utf-8")
    if json_output:
        print(json.dumps({"output_path": str(out_path), "days": merged["days"]}))
    else:
        print(f"merged {merged['days']} days -> {out_path}")


def _shift(day: str, n: int) -> str:
    import datetime

    d = datetime.date.fromisoformat(day)
    return (d - datetime.timedelta(days=n)).isoformat()


@app.command("status")
def status(json_output: bool = typer.Option(False, "--json")) -> None:
    """Show whether capture/server/llama are up and today's frame count."""
    data = _client(_cfg).get("/status")
    if json_output:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    srv = data["server"]
    print(f"server: {srv['status']} (v{srv['version']}, up {srv['uptime_s']}s)")
    print(f"db: {data['db']['frames_today']} frames today, {data['db']['size_bytes']} bytes")
    cap = data["capture"]
    print(f"capture: {'alive' if cap['alive'] else 'DOWN'}")
    print(f"llama: {'up' if data['llama']['reachable'] else 'down'}")
    for name, ts in data["pipes"]["last_runs"].items():
        print(f"last {name}: {ts or 'never'}")


def main(argv: list[str] | None = None) -> None:
    try:
        app(args=argv or sys.argv[1:], prog_name="heimdall", standalone_mode=False)
    except click.exceptions.Exit as exc:
        raise SystemExit(exc.exit_code)
    except ApiError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise SystemExit(1)
