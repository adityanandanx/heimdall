"""Secondary seam: pipe parse/render + deterministic multi-day merge."""

from __future__ import annotations

import json

import httpx
import pytest

from heimdall.config import Config
from heimdall.db import Database, init_db
from heimdall.observability import TraceGate
from heimdall.pipes.llm import LlmClient
from heimdall.pipes.parse import (
    PipeValidationError,
    parse_breakdown,
    parse_recap,
    strip_fences,
)
from heimdall.pipes.prompts import DB_SEARCH_TOOL, PromptOverBudget, build_recap_prompt
from heimdall.pipes.recap import _tool_args, run as run_recap
from heimdall.pipes.render import render_breakdown, render_recap
from heimdall.pipes.merge import parse_breakdown_table, merge
from heimdall.timeutil import day_bounds


def test_strip_fences():
    assert strip_fences("```json\n{\"a\": 1}\n```") == '{"a": 1}'
    assert strip_fences("```\n{\"a\": 1}\n```") == '{"a": 1}'
    assert strip_fences('{"a": 1}') == '{"a": 1}'


def test_parse_recap_fences_and_wrapper():
    recap = parse_recap('```json\n{"date": "2026-08-02", "summary": "s", '
                        '"accomplishments": ["a"], "unfinished": [], "standout": []}\n```')
    assert recap["date"] == "2026-08-02"
    wrapped = parse_recap('{"day_recap": {"date": "2026-08-02", "summary": "s", '
                          '"accomplishments": ["a"], "unfinished": [], "standout": []}}')
    assert wrapped["summary"] == "s"


def test_parse_recap_missing_key():
    with pytest.raises(PipeValidationError):
        parse_recap('{"date": "x", "summary": "s", "accomplishments": [], "unfinished": []}')


def test_parse_recap_malformed():
    with pytest.raises(PipeValidationError):
        parse_recap("not json at all")


def test_parse_breakdown_shape():
    text = json.dumps({"categories": [
        {"category": "Music", "minutes": 10, "evidence": "tracks"},
    ]})
    out = parse_breakdown(text)
    assert out["categories"][0]["minutes"] == 10


def test_parse_breakdown_bad():
    with pytest.raises(PipeValidationError):
        parse_breakdown('{"foo": 1}')


def test_build_recap_prompt_titles_always_present():
    frames = [{"ts": 1, "window_class": "a", "window_title": "one", "ocr_text": "x" * 1000},
              {"ts": 2, "window_class": "b", "window_title": "two", "ocr_text": "y" * 1000}]
    prompt = build_recap_prompt(frames, "2026-08-02", budget_tokens=50)
    assert "| a | one" in prompt
    assert "| b | two" in prompt
    assert "ocr:" not in prompt  # tiny budget: title lines only, no OCR snippets
    prompt2 = build_recap_prompt(frames, "2026-08-02", budget_tokens=200)
    assert "ocr:" in prompt2  # budget fits at least one snippet
    assert "| a | one" in prompt2 and "| b | two" in prompt2  # frames never dropped


def test_build_recap_prompt_over_budget_raises():
    frames = [{"ts": i, "window_class": "kitty", "window_title": "t" * 200,
               "ocr_text": ""} for i in range(5000)]
    with pytest.raises(ValueError):
        build_recap_prompt(frames, "2026-08-02", budget_tokens=6000)


# ---- over-budget day: FTS5 db_search agent loop (spec #4) ----

def test_complete_tools_returns_tool_calls():
    """LlmClient.complete_tools passes `tools` and returns the raw assistant
    message, tool_calls included."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "tools" in body
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "db_search",
                                         "arguments": '{"query": "rust"}'}}],
        }}]})

    llm = LlmClient("http://x", "m", transport=httpx.MockTransport(handler))
    msg = llm.complete_tools([{"role": "user", "content": "hi"}], [DB_SEARCH_TOOL])
    call = msg["tool_calls"][0]
    assert call["function"]["name"] == "db_search"
    assert json.loads(call["function"]["arguments"]) == {"query": "rust"}


def test_recap_agent_path_on_over_budget_day(tmp_path):
    """A day whose title-only prompt exceeds context must go through the
    FTS5 db_search tool loop instead of truncating (#4)."""
    db_path = tmp_path / "data.db"
    init_db(db_path)
    db = Database(db_path)
    start_ms, _ = day_bounds("2026-08-02")
    for i in range(5000):
        db.insert_frame({
            "ts": start_ms + i,
            "monitor": 0,
            "workspace": 2,
            "window_class": "kitty",
            "window_title": "t" * 200,
            "fullscreen": 0,
            "trigger": "keepalive",
            "image_path": "frames/2026/08/02/x.jpg",
            "image_bytes": 0,
            "ocr_text": "",
            "ocr_sec": 0.0,
        })

    calls = {"n": 0}
    tool_results: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls["n"] += 1
        roles = [m["role"] for m in body["messages"]]
        if "tool" in roles:
            tool_results.append(body["messages"][-1]["content"])
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant",
                "content": json.dumps({
                    "date": "2026-08-02", "summary": "Agentic recap over FTS5.",
                    "accomplishments": ["Gathered evidence via db_search"],
                    "unfinished": [], "standout": []})}}]})
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "db_search",
                                         "arguments": json.dumps(
                                             {"query": "rust", "limit": 5})}}]}}]})

    llm = LlmClient("http://x", "m", transport=httpx.MockTransport(handler))
    cfg = Config(data_dir=tmp_path)
    result = run_recap(day="2026-08-02", db_path=db_path, llm=llm,
                       gate=TraceGate(False), config=cfg)
    assert calls["n"] == 2
    assert result["mode"] == "agent"
    assert tool_results and "no results" in tool_results[0]
    assert "Agentic recap over FTS5." in result["markdown"]


def test_recap_agent_bad_query_is_survivable(tmp_path):
    """An invalid FTS5 MATCH from the model is fed back as an error tool result,
    not an uncaught sqlite error (token-tolerant retrieval)."""
    db_path = tmp_path / "data.db"
    init_db(db_path)
    db = Database(db_path)
    start_ms, _ = day_bounds("2026-08-02")
    for i in range(5000):
        db.insert_frame({
            "ts": start_ms + i, "monitor": 0, "workspace": 2,
            "window_class": "kitty", "window_title": "t" * 200,
            "fullscreen": 0, "trigger": "keepalive", "image_path": "f.jpg",
            "image_bytes": 0, "ocr_text": "rust is cool", "ocr_sec": 0.0,
        })

    calls = {"n": 0}
    tool_results: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls["n"] += 1
        if "tool" in [m["role"] for m in body["messages"]]:
            tool_results.append(body["messages"][-1]["content"])
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant",
                "content": json.dumps({
                    "date": "2026-08-02", "summary": "s", "accomplishments": [],
                    "unfinished": [], "standout": []})}}]})
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "db_search",
                                         "arguments": '{"query": "NEAR(nonsense"}'}}]}}]})

    llm = LlmClient("http://x", "m", transport=httpx.MockTransport(handler))
    cfg = Config(data_dir=tmp_path)
    result = run_recap(day="2026-08-02", db_path=db_path, llm=llm,
                       gate=TraceGate(False), config=cfg)
    assert "error" in tool_results[0]


def test_tool_args_requires_json_object():
    """Malformed or non-object tool arguments raise PromptOverBudget, which the
    agent loop feeds back as an error tool result instead of crashing."""
    assert _tool_args({"function": {"arguments": '{"query": "x"}'}}) == {"query": "x"}
    assert _tool_args({}) == {}
    assert _tool_args({"function": {}}) == {}
    with pytest.raises(PromptOverBudget):
        _tool_args({"function": {"arguments": "[1, 2]"}})
    with pytest.raises(PromptOverBudget):
        _tool_args({"function": {"arguments": "not json"}})


def test_recap_agent_malformed_tool_args_fed_back(tmp_path):
    """A tool_call whose arguments are a JSON list (not an object) is fed back
    as an error tool result, and the loop still finishes with a recap."""
    db_path = tmp_path / "data.db"
    init_db(db_path)
    db = Database(db_path)
    start_ms, _ = day_bounds("2026-08-02")
    for i in range(5000):
        db.insert_frame({
            "ts": start_ms + i, "monitor": 0, "workspace": 2,
            "window_class": "kitty", "window_title": "t" * 200,
            "fullscreen": 0, "trigger": "keepalive", "image_path": "f.jpg",
            "image_bytes": 0, "ocr_text": "", "ocr_sec": 0.0,
        })

    tool_results: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "tool" in [m["role"] for m in body["messages"]]:
            tool_results.append(body["messages"][-1]["content"])
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant",
                "content": json.dumps({
                    "date": "2026-08-02", "summary": "s", "accomplishments": [],
                    "unfinished": [], "standout": []})}}]})
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "db_search",
                                         "arguments": "[1, 2]"}}]}}]})

    llm = LlmClient("http://x", "m", transport=httpx.MockTransport(handler))
    cfg = Config(data_dir=tmp_path)
    result = run_recap(day="2026-08-02", db_path=db_path, llm=llm,
                       gate=TraceGate(False), config=cfg)
    assert "must be a JSON object" in tool_results[0]
    assert result["output_path"].endswith("day-recap-2026-08-02.md")


def test_recap_agent_turn_exhaustion_forces_final_recap(tmp_path):
    """A model that never finishes with an answer still yields a recap: after
    MAX_AGENT_TURNS tool loops the runner forces a final completion over the
    evidence gathered (no truncation, no crash)."""
    db_path = tmp_path / "data.db"
    init_db(db_path)
    db = Database(db_path)
    start_ms, _ = day_bounds("2026-08-02")
    for i in range(5000):
        db.insert_frame({
            "ts": start_ms + i, "monitor": 0, "workspace": 2,
            "window_class": "kitty", "window_title": "t" * 200,
            "fullscreen": 0, "trigger": "keepalive", "image_path": "f.jpg",
            "image_bytes": 0, "ocr_text": "rust", "ocr_sec": 0.0,
        })

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls["n"] += 1
        if "tools" in body:
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": f"call_{calls['n']}", "type": "function",
                                "function": {"name": "db_search",
                                             "arguments": '{"query": "rust"}'}}]}}]})
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant",
            "content": json.dumps({
                "date": "2026-08-02", "summary": "final after turns",
                "accomplishments": [], "unfinished": [], "standout": []})}}]})

    llm = LlmClient("http://x", "m", transport=httpx.MockTransport(handler))
    cfg = Config(data_dir=tmp_path)
    result = run_recap(day="2026-08-02", db_path=db_path, llm=llm,
                       gate=TraceGate(False), config=cfg)
    assert result["mode"] == "agent"
    assert calls["n"] == 7  # MAX_AGENT_TURNS tool calls + 1 forced completion
    assert "final after turns" in result["markdown"]


def test_render_recap_front_matter_and_sections():
    md = render_recap(
        {"date": "2026-08-02", "summary": "s", "accomplishments": ["did a"],
         "unfinished": ["todo b"], "standout": ["learned c"]},
        date="2026-08-02", range_="r", generated_at="g", frame_count=5, trace_url="http://t",
    )
    assert md.startswith("---\n")
    assert "title: Day recap" in md
    assert "date: 2026-08-02" in md
    assert "frame_count: 5" in md
    assert "trace_url: \"http://t\"" in md
    assert "## What I did" in md and "- did a" in md
    assert "## Unfinished / to pick up" in md and "- todo b" in md
    assert "## Standout" in md and "- learned c" in md


def test_render_breakdown_table_and_merge_roundtrip():
    minutes = {"Building projects": 30, "Music": 10, "Other": 5}
    evidence = {"Music": "exact playback spans from 2 track events"}
    md = render_breakdown(minutes, evidence, date="2026-08-02", range_="r",
                          generated_at="g", frame_count=3)
    assert "| Category | Minutes |" in md
    assert "| Building projects | 30 |" in md
    assert "**Total:** 45 minutes" in md
    assert "_Movie and music time derives from playback/title spans" in md
    parsed = parse_breakdown_table(md)
    assert parsed == minutes


def test_merge_two_days(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "time-breakdown-2026-08-02.md").write_text(render_breakdown(
        {"Building projects": 30, "Music": 10, "Other": 5}, {"Music": "x"},
        date="2026-08-02", range_="r", generated_at="g", frame_count=3))
    (out / "time-breakdown-2026-08-03.md").write_text(render_breakdown(
        {"Building projects": 50, "YouTube": 20, "Other": 5}, {},
        date="2026-08-03", range_="r", generated_at="g", frame_count=4))
    result = merge(out, 2)
    assert result["days"] == 2
    assert result["end_day"] == "2026-08-03"
    md = result["markdown"]
    assert "## Totals" in md
    assert "| Building projects | 80 | 2026-08-03 (50) |" in md
    assert "## Per day" in md
    assert "| Category | 2026-08-02 | 2026-08-03 | Total |" in md
    assert "**Grand total:** 120 minutes" in md


def test_merge_no_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        merge(tmp_path / "output", 3)


def test_merge_reports_requested_days_not_file_count(tmp_path):
    """The filename is {endday}-{N}d.md where N is the REQUESTED --days, even
    if fewer day-files exist (spec #9)."""
    out = tmp_path / "output"
    out.mkdir()
    (out / "time-breakdown-2026-08-02.md").write_text(render_breakdown(
        {"Building projects": 30, "Music": 10}, {}, date="2026-08-02",
        range_="r", generated_at="g", frame_count=3))
    (out / "time-breakdown-2026-08-03.md").write_text(render_breakdown(
        {"Building projects": 50, "YouTube": 20}, {}, date="2026-08-03",
        range_="r", generated_at="g", frame_count=4))
    result = merge(out, 3)
    assert result["days"] == 3
    assert result["end_day"] == "2026-08-03"
    assert "**Grand total:** 110 minutes" in result["markdown"]
