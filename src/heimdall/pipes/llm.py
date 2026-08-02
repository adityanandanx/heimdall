"""LLM access: one httpx client to llama-server's OpenAI-compatible endpoint.

`gate` (a TraceGate) wraps each completion in a generation span; it is a no-op
when tracing is disabled or the gate is None.
"""

from __future__ import annotations

from contextlib import nullcontext

import httpx

from heimdall.observability import TraceGate

DEFAULT_TIMEOUT = 300.0


class LlmClient:
    """Thin wrapper over /v1/chat/completions.

    `transport` is injectable (httpx.MockTransport in tests). `model` is sent
    verbatim; llama-server accepts any id here.
    """

    def __init__(self, base_url: str, model: str,
                 transport: httpx.AsyncBaseTransport | None = None,
                 gate: TraceGate | None = None):
        self.model = model
        self.gate = gate
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=DEFAULT_TIMEOUT,
            transport=transport or httpx.HTTPTransport(retries=1),
        )

    def _generation(self, name: str, messages: list[dict], gate: TraceGate | None = None):
        gate = gate or self.gate
        if gate is None:
            return nullcontext()
        return gate.generation(name, model=self.model, input=messages[-1] if messages else None)

    def complete(self, messages: list[dict], response_format: dict,
                 gate: TraceGate | None = None) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "stream": False,
            "response_format": response_format,
        }
        with self._generation("llm-complete", messages, gate):
            r = self._client.post("/v1/chat/completions", json=payload)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]

    def complete_tools(self, messages: list[dict], tools: list[dict],
                       gate: TraceGate | None = None) -> dict:
        """Tool-calling completion; returns the raw assistant message dict so the
        caller can echo `tool_calls` verbatim and append tool results."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "stream": False,
            "tools": tools,
        }
        with self._generation("llm-complete-tools", messages, gate):
            r = self._client.post("/v1/chat/completions", json=payload)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]

    def close(self) -> None:
        self._client.close()
