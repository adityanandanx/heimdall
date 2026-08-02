"""CLI tests: thin HTTP client contract (commands ride the API seam)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from heimdall import cli
from heimdall.pipes.render import render_breakdown


def mock_api_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/search":
            return httpx.Response(200, json={
                "total": 2,
                "items": [
                    {"id": 1, "ts": 1000, "window_class": "firefox",
                     "window_title": "youtube.com/watch?v=x", "workspace": "2:2",
                     "image_path": "frames/2026/08/02/1.jpg",
                     "snippet": "watching **rick astley**", "score": -1.2},
                    {"id": 2, "ts": 2000, "window_class": "code",
                     "window_title": "capture.py — heimdall", "workspace": "2:2",
                     "image_path": "frames/2026/08/02/2.jpg",
                     "snippet": "event loop", "score": -0.8},
                ],
            })
        if path == "/pipes/run/day-recap":
            return httpx.Response(200, json={
                "pipe": "day-recap", "ts": "2026-08-02T20:00:00+05:30", "run_ms": 1000,
                "output_markdown": "# Day recap", "output_path": "output/day-recap-2026-08-02.md",
                "trace_url": "http://localhost:3000/traces/1", "frame_count": 3,
            })
        if path == "/pipes/run/time-breakdown":
            return httpx.Response(200, json={
                "pipe": "time-breakdown", "ts": "2026-08-02T20:00:00+05:30", "run_ms": 1000,
                "output_markdown": "# Time breakdown", "output_path": "output/time-breakdown-2026-08-02.md",
                "trace_url": "", "frame_count": 3,
            })
        if path == "/status":
            return httpx.Response(200, json={
                "server": {"status": "ok", "version": "0.1.0", "uptime_s": 12},
                "db": {"frames_today": 8, "size_bytes": 4096},
                "capture": {"alive": True, "last_event_ts": 1785700000000},
                "llama": {"reachable": True},
                "pipes": {"last_runs": {"day-recap": None, "time-breakdown": "2026-08-02T23:05:00+05:30"}},
            })
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"data_dir": str(tmp_path)}))
    return path


def run_cli(argv: list[str], config_path: Path, transport: httpx.MockTransport, capsys):
    cli._client_factory = lambda cfg, _: cli.ApiClient("http://127.0.0.1:1", transport=transport)
    try:
        cli.main(["--config", str(config_path)] + argv)
    finally:
        cli._client_factory = None
    return capsys.readouterr().out


def test_search_renders_lines(config_path, capsys):
    out = run_cli(["search", "youtube"], config_path, mock_api_transport(), capsys)
    assert "youtube.com/watch?v=x" in out
    assert "rick astley" in out
    assert "2 result(s)" in out


def test_search_json_flag(config_path, capsys):
    out = run_cli(["search", "youtube", "--json"], config_path, mock_api_transport(), capsys)
    body = json.loads(out)
    assert set(body) == {"total", "items"}
    assert body["total"] == 2


def test_recap_posts_to_api(config_path, capsys):
    out = run_cli(["recap", "yesterday"], config_path, mock_api_transport(), capsys)
    assert "wrote output/day-recap-2026-08-02.md" in out
    assert "trace: http://localhost:3000/traces/1" in out


def test_run_generic_pipe(config_path, capsys):
    out = run_cli(["run", "day-recap", "--day", "2026-08-02"], config_path, mock_api_transport(), capsys)
    assert "day-recap" in out


def test_status_renders(config_path, capsys):
    out = run_cli(["status"], config_path, mock_api_transport(), capsys)
    assert "server: ok" in out
    assert "8 frames today" in out
    assert "capture: alive" in out
    assert "llama: up" in out
    assert "last time-breakdown: 2026-08-02T23:05:00+05:30" in out


def test_breakdown_single_day(config_path, capsys):
    out = run_cli(["breakdown", "2026-08-02"], config_path, mock_api_transport(), capsys)
    assert "wrote output/time-breakdown-2026-08-02.md" in out


def test_breakdown_multi_day_merges_locally(config_path, capsys):
    out_dir = config_path.parent / "output"
    out_dir.mkdir()
    for day, minutes in (("2026-08-02", {"Music": 10, "Other": 5}),
                         ("2026-08-03", {"Music": 20, "Other": 5})):
        (out_dir / f"time-breakdown-{day}.md").write_text(render_breakdown(
            minutes, {}, date=day, range_="r", generated_at="g", frame_count=2))
    out = run_cli(["breakdown", "2026-08-03", "--days", "2"], config_path, mock_api_transport(), capsys)
    merged = out_dir / "time-breakdown-2026-08-03-2d.md"
    assert merged.exists()
    assert "merged 2 days" in out
    assert "| Music | 30 |" in merged.read_text()


def test_api_error_exits_nonzero(config_path, capsys):
    transport = httpx.MockTransport(
        lambda r: httpx.Response(404, json={"detail": "unknown pipe 'nope'"}))
    with pytest.raises(SystemExit) as exc:
        run_cli(["run", "nope"], config_path, transport, capsys)
    assert exc.value.code == 1
