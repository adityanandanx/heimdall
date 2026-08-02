"""Optional self-hosted Langfuse tracing (spec ticket #12).

No-op by default: tracing only activates when `observability.enabled` is true in
config AND the LANGFUSE_* env vars are set. Pipes never depend on this module;
imports are lazy so the core works without langfuse installed.
"""

from __future__ import annotations

import functools
import os
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)

_ENV_KEYS = ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")


def env_configured() -> bool:
    return all(os.environ.get(k) for k in _ENV_KEYS)


class TraceGate:
    """Gates @observe-style tracing for one pipe run."""

    def __init__(self, enabled: bool):
        self.enabled = bool(enabled) and env_configured()

    def decorate(self, name: str) -> Callable[[F], F]:
        if not self.enabled:
            def passthrough(fn: F) -> F:
                return fn
            return passthrough
        try:
            from langfuse.decorators import observe
        except ImportError:
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

    def flush(self) -> None:
        if not self.enabled:
            return
        try:
            from langfuse._client.get_client import get_client
            get_client().flush()
        except Exception:
            pass


def decorate(fn: F, name: str) -> F:
    """Convenience for callers without a TraceGate."""
    return TraceGate(env_configured()).decorate(name)(fn)


@functools.lru_cache(maxsize=1)
def trace_gate(enabled: bool | None = None) -> TraceGate:
    return TraceGate(env_configured() if enabled is None else enabled)
