"""Observability gate: tracing activates only when config, env, package and
server all line up, and degrades to a no-op otherwise."""

from __future__ import annotations

import httpx
import pytest

import heimdall.observability as obs

from conftest import FIXTURE_DAY, RECAP_COMPLETION, build_day_db, mock_llm_response
from heimdall.config import Config
from heimdall.pipes.llm import LlmClient


def _gate(monkeypatch, enabled=True, installed=True, reachable=True, env=True):
    monkeypatch.setattr(obs, "_langfuse_installed", lambda: installed)
    monkeypatch.setattr(obs, "_langfuse_reachable", lambda: reachable)
    if env:
        monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:3000")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    else:
        monkeypatch.delenv("LANGFUSE_HOST", raising=False)
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    return obs.TraceGate(enabled)


def test_disabled_by_config(monkeypatch):
    gate = _gate(monkeypatch, enabled=False)
    assert not gate.enabled
    assert gate.reason == "disabled by config"


def test_env_unset(monkeypatch):
    gate = _gate(monkeypatch, env=False)
    assert not gate.enabled
    assert gate.reason == "LANGFUSE_* env vars unset"


def test_package_not_installed(monkeypatch):
    gate = _gate(monkeypatch, installed=False)
    assert not gate.enabled
    assert gate.reason == "langfuse not installed"


def test_server_unreachable(monkeypatch):
    gate = _gate(monkeypatch, reachable=False)
    assert not gate.enabled
    assert gate.reason == "langfuse server unreachable"


def test_all_conditions_met(monkeypatch):
    gate = _gate(monkeypatch)
    assert gate.enabled
    assert gate.reason == ""


def test_decorate_passthrough_when_disabled(monkeypatch):
    gate = _gate(monkeypatch, env=False)
    fn = lambda: "ok"  # noqa: E731
    assert gate.decorate("pipe-day-recap")(fn) is fn


def test_decorate_import_error_falls_back(monkeypatch):
    gate = _gate(monkeypatch)  # gate claims enabled, but langfuse isn't installed
    fn = lambda: "x"  # noqa: E731
    assert gate.decorate("pipe-day-recap")(fn) is fn
    assert not gate.enabled
    assert gate.reason == "langfuse not installed"


# ---- span / generation / metadata are strict no-ops when disabled ----

def _assert_no_langfuse_import(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def guarded(name, *a, **k):
        if name == "langfuse" or name.startswith("langfuse."):
            raise AssertionError("langfuse must not be imported when tracing is off")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", guarded)


def test_span_noop_when_disabled(monkeypatch):
    _assert_no_langfuse_import(monkeypatch)
    gate = _gate(monkeypatch, env=False)
    with gate.span("parse-recap") as span:
        assert span is None
    with gate.generation("llm-complete", model="m", input={"x": 1}) as gen:
        assert gen is None
    gate.metadata(db_queries=3)  # must not raise


def test_span_import_error_falls_back(monkeypatch):
    gate = _gate(monkeypatch)  # enabled per gate, but langfuse import fails
    import builtins

    real_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__",
                        lambda name, *a, **k: (_ for _ in ()).throw(ImportError())
                        if name == "langfuse" or name.startswith("langfuse.")
                        else real_import(name, *a, **k))
    with gate.span("parse-recap") as span:
        assert span is None
    with gate.generation("llm-complete", model="m") as gen:
        assert gen is None
    gate.metadata(db_queries=3)


# ---- instrumentation wiring: pipes + LLM client report spans/counts ----

class RecordingGate(obs.TraceGate):
    """Fake enabled gate that records span/generation/metadata calls — proves
    the pipes and LlmClient actually instrument their steps."""

    def __init__(self):
        super().__init__(False)
        self.enabled = True
        self.reason = ""
        self.events: list[tuple[str, dict]] = []
        self.meta: dict = {}
        self._stack: list[str] = []

    def span(self, name: str):
        self.events.append(("span", {"name": name}))
        self._stack.append(name)
        return _Ctx(lambda: self._stack.pop())

    def generation(self, name: str, *, model: str = "", input=None, output=None):
        self.events.append(("generation", {"name": name, "model": model}))
        self._stack.append(name)
        return _Ctx(lambda: self._stack.pop())

    def metadata(self, **kwargs):
        self.meta.update(kwargs)

    @property
    def active(self) -> list[str]:
        return list(self._stack)


class _Ctx:
    def __init__(self, on_exit):
        self._on_exit = on_exit

    def __enter__(self):
        return None

    def __exit__(self, *exc):
        self._on_exit()
        return False


def test_recap_pipe_reports_parse_span_and_db_queries(tmp_path, monkeypatch):
    from heimdall.pipes.core import run_pipe

    data_dir = tmp_path / "data"
    db_path = data_dir / "data.db"
    build_day_db(db_path)
    gate = RecordingGate()
    llm = LlmClient("http://x", "m",
                    transport=mock_llm_response(RECAP_COMPLETION))
    cfg = Config(data_dir=data_dir)
    result = run_pipe("day-recap", day=FIXTURE_DAY, config=cfg, db_path=db_path,
                      llm=llm, gate=gate)
    assert gate.meta.get("db_queries", 0) >= 1
    assert any(e[0] == "span" and e[1]["name"] == "parse-recap" for e in gate.events)
    assert result["output_path"].endswith(f"day-recap-{FIXTURE_DAY}.md")


def test_llm_complete_wraps_in_generation_span():
    llm = LlmClient("http://x", "m", transport=mock_llm_response(RECAP_COMPLETION),
                    gate=RecordingGate())
    out = llm.complete([{"role": "user", "content": "x"}], {})
    assert out
    assert any(e[0] == "generation" and e[1]["name"] == "llm-complete"
               for e in llm.gate.events)
    assert llm.gate.active == []


def test_llm_complete_reports_error_in_generation_span():
    class Boom(Exception):
        pass

    def handler(request):
        raise Boom("server down")

    gate = RecordingGate()
    llm = LlmClient("http://x", "m", transport=httpx.MockTransport(handler), gate=gate)
    with pytest.raises(Boom):
        llm.complete([{"role": "user", "content": "x"}], {})
    assert any(e[0] == "generation" and e[1]["name"] == "llm-complete"
               for e in gate.events)
    assert gate.active == []  # span exited cleanly even on error
