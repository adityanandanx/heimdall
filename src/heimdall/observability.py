"""Optional self-hosted Langfuse tracing (spec ticket #12).

No-op by default: tracing only activates when `observability.enabled` is true in
config AND the LANGFUSE_* env vars are set AND the langfuse package is installed
AND the Langfuse server answers a health probe. Pipes never depend on this
module; imports are lazy so the core works without langfuse installed.
"""

from __future__ import annotations

import functools
import importlib.util
import logging
import os
from contextlib import nullcontext
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)

_ENV_KEYS = ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")

log = logging.getLogger("heimdall.trace")


def env_configured() -> bool:
    return all(os.environ.get(k) for k in _ENV_KEYS)


def _langfuse_installed() -> bool:
    return importlib.util.find_spec("langfuse") is not None


def _langfuse_reachable() -> bool:
    """One short health probe per host, remembered for the process lifetime."""
    host = os.environ.get("LANGFUSE_HOST", "")
    if host not in _probed:
        try:
            import httpx

            with httpx.Client(base_url=host.rstrip("/"), timeout=1.5) as c:
                r = c.get("/api/public/health")
            _probed[host] = r.status_code == 200
        except Exception:  # noqa: BLE001
            _probed[host] = False
        if not _probed[host]:
            log.warning("langfuse at %s is unreachable; tracing disabled", host)
    return _probed[host]


_probed: dict[str, bool] = {}


class TraceGate:
    """Gates @observe-style tracing for one pipe run.

    `enabled` is true only when config, env, package and server all line up.
    `reason` explains why tracing is off — surfaced in /status.
    """

    def __init__(self, enabled: bool):
        self.reason = "disabled by config"
        if enabled and not env_configured():
            self.reason = "LANGFUSE_* env vars unset"
        elif enabled and not _langfuse_installed():
            self.reason = "langfuse not installed"
        elif enabled and not _langfuse_reachable():
            self.reason = "langfuse server unreachable"
        elif enabled:
            self.reason = ""
        self.enabled = bool(enabled) and self.reason == ""

    def decorate(self, name: str) -> Callable[[F], F]:
        if not self.enabled:
            def passthrough(fn: F) -> F:
                return fn
            return passthrough
        try:
            from langfuse.decorators import observe
        except ImportError:
            self.enabled = False
            self.reason = "langfuse not installed"

            def passthrough(fn: F) -> F:
                return fn
            return passthrough
        return observe(name=name)

    def trace_url(self) -> str:
        if not self.enabled:
            return ""
        try:
            from langfuse._client.get_client import get_client
            return get_client().get_trace_url() or ""
        except Exception:
            return ""

    def span(self, name: str):
        """A named child span on the current trace (parse steps, db_search...)."""
        if not self.enabled:
            return nullcontext()
        try:
            from langfuse.decorators import create_span
        except ImportError:
            return nullcontext()
        return create_span(name=name)

    def generation(self, name: str, *, model: str = "", input=None, output=None):
        """A generation span for an LLM completion call."""
        if not self.enabled:
            return nullcontext()
        try:
            from langfuse.decorators import create_generation
        except ImportError:
            return nullcontext()
        return create_generation(name=name, model=model, input=input, output=output)

    def metadata(self, **kwargs) -> None:
        """Attach counts/context (e.g. db_queries) to the current trace."""
        if not self.enabled:
            return
        try:
            from langfuse.decorators import langfuse_context
            langfuse_context.update_current_trace(metadata=kwargs)
        except Exception:
            pass

    def flush(self) -> None:
        if not self.enabled:
            return
        try:
            from langfuse._client.get_client import get_client
            get_client().flush()
        except Exception:
            pass


@functools.lru_cache(maxsize=1)
def trace_gate(enabled: bool | None = None) -> TraceGate:
    return TraceGate(env_configured() if enabled is None else enabled)
