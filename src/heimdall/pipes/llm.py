"""LLM access: one httpx client to llama-server's OpenAI-compatible endpoint."""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT = 300.0


class LlmClient:
    """Thin wrapper over /v1/chat/completions.

    `transport` is injectable (httpx.MockTransport in tests). `model` is sent
    verbatim; llama-server accepts any id here.
    """

    def __init__(self, base_url: str, model: str, transport: httpx.AsyncBaseTransport | None = None):
        self.model = model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=DEFAULT_TIMEOUT,
            transport=transport or httpx.HTTPTransport(retries=1),
        )

    def complete(self, messages: list[dict], response_format: dict) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "stream": False,
            "response_format": response_format,
        }
        r = self._client.post("/v1/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]

    def close(self) -> None:
        self._client.close()
