"""Secondary seam: pipe parse/render + deterministic multi-day merge."""

from __future__ import annotations

import json

import pytest

from heimdall.pipes.parse import (
    PipeValidationError,
    parse_breakdown,
    parse_recap,
    strip_fences,
)
from heimdall.pipes.prompts import build_recap_prompt
from heimdall.pipes.render import render_breakdown, render_recap
from heimdall.pipes.merge import parse_breakdown_table, merge


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
