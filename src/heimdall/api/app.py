"""FastAPI application factory for heimdall (primary testing seam).

Injects config, a fixture DB path and an LLM transport so tests can run the
whole HTTP surface against a temp database with the LLM mocked.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from heimdall import __version__
from heimdall.api.routers import (capture_router, health_router, search_router,
                                  frames_router, pipes_router, status_router,
                                  sessions_router)
from heimdall.capture.asr import AsrManager
from heimdall.config import Config
from heimdall.db import Database, init_db
from heimdall.pipes.llm import LlmClient
from heimdall.scheduler import start_scheduler as start_scheduler_fn


def create_app(config: Config, *, db_path: str | Path | None = None,
               llm_transport: httpx.AsyncBaseTransport | None = None,
               list_players: Callable[[], list[dict]] | None = None,
               start_scheduler: bool = False,
               config_path: str | Path | None = None) -> FastAPI:
    data = config.data_path
    db_path = Path(db_path) if db_path else data / "data.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db(db_path)

    llm = LlmClient(config.llama_server.base_url, config.llama_server.model, transport=llm_transport)

    app = FastAPI(title="heimdall", version=__version__)
    # loopback-only bind is the security boundary; prototypes (v2/v3) run on
    # a different local port and fetch this API from the browser, so allow any
    # origin instead of persisting per-origin allowances
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.config = config
    app.state.config_path = str(config_path) if config_path else None
    app.state.db_path = db_path
    app.state.db = Database(db_path)
    app.state.llm = llm
    app.state.started = time.time()
    app.state.last_runs: dict[str, str] = {}
    app.state.transport = llm_transport
    app.state.list_players = list_players
    app.state.asr = AsrManager(config, app.state.db)

    app.include_router(health_router)
    app.include_router(search_router)
    app.include_router(frames_router)
    app.include_router(pipes_router)
    app.include_router(status_router)
    app.include_router(sessions_router)
    app.include_router(capture_router)

    if start_scheduler:
        start_scheduler_fn(app)

    return app
