"""Langfuse self-hosted wiring for the pipe prototypes. PROTOTYPE — wipe me.

Credentials default to the local Langfuse stack stood up for the ticket #4
experiment (see /tmp/opencode/langfuse/.env). Override via env vars.
"""

import os
import time

LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "pk-lf-13c1f61800492f49")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "sk-lf-a6c591c85c540b6dbea58c0fa4e7751e")

os.environ["LANGFUSE_HOST"] = LANGFUSE_HOST
os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY


def client():
    from langfuse._client.get_client import get_client

    return get_client()


def trace_url() -> str | None:
    return client().get_trace_url()


def finish() -> None:
    client().flush()
    time.sleep(3)
