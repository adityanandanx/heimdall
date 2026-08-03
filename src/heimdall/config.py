"""Configuration loading for heimdall.

Defaults live in code; a `config.yaml` under the data dir overrides them.
Unknown keys warn (never error). Secrets stay env-only (LANGFUSE_*).
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_DATA_DIR = "~/.heimdall"
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.heimdall/config.yaml")


@dataclass
class ApiConfig:
    bind: str = "127.0.0.1"
    port: int = 3030


@dataclass
class LlamaConfig:
    base_url: str = "http://127.0.0.1:8080"
    model: str = "gemma-4-E2B-it-qat-q4_0"


@dataclass
class CaptureConfig:
    debounce_s: float = 1.5
    min_interval_s: float = 10
    keepalive_min: float = 5
    extract_workers: int = 1
    extraction: str = "auto"  # auto|a11y|ocr; auto = content-bearing test, a11y wins, else NULL (rapid in #34)


@dataclass
class SchedulerConfig:
    day_recap: str = "0 23 * * *"
    time_breakdown: str = "5 23 * * *"


@dataclass
class ObservabilityConfig:
    enabled: bool = True


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(os.path.expanduser(DEFAULT_DATA_DIR)))
    api: ApiConfig = field(default_factory=ApiConfig)
    llama_server: LlamaConfig = field(default_factory=LlamaConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    rules: dict = field(default_factory=lambda: {"window_class_category": {"sidra": "Music", "mpv": "Movies"}})
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)

    @property
    def data_path(self) -> Path:
        """Absolute data dir."""
        return self.data_dir.expanduser()

    @property
    def db_path(self) -> Path:
        return self.data_path / "data.db"

    @property
    def output_path(self) -> Path:
        return self.data_path / "output"

    @property
    def frames_path(self) -> Path:
        return self.data_path / "frames"

    @property
    def window_class_category(self) -> dict:
        return self.rules.get("window_class_category", {}) if self.rules else {}


def _warn_unknown(section: str, known: set[str], given: dict) -> None:
    for key in given:
        if key not in known:
            warnings.warn(f"config.yaml: unknown key {section}.{key} ignored")


def _scalar(name, given, default):
    if name in given:
        return given[name]
    return default


def load_config(path: str | None = None) -> Config:
    """Load config from a yaml file (default: ~/.heimdall/config.yaml).

    Missing file or keys fall back to code defaults. Unknown keys warn.
    """
    path = path or DEFAULT_CONFIG_PATH
    cfg = Config()
    if not os.path.exists(path):
        return cfg
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    _warn_unknown("", {"data_dir", "api", "llama_server", "capture", "scheduler", "rules", "observability"}, raw)

    if "data_dir" in raw:
        cfg.data_dir = Path(raw["data_dir"])
    if "api" in raw:
        api = raw["api"] or {}
        _warn_unknown("api", {"bind", "port"}, api)
        cfg.api = ApiConfig(
            bind=_scalar("bind", api, cfg.api.bind),
            port=_scalar("port", api, cfg.api.port),
        )
    if "llama_server" in raw:
        ls = raw["llama_server"] or {}
        _warn_unknown("llama_server", {"base_url", "model"}, ls)
        cfg.llama_server = LlamaConfig(
            base_url=_scalar("base_url", ls, cfg.llama_server.base_url),
            model=_scalar("model", ls, cfg.llama_server.model),
        )
    if "capture" in raw:
        cap = raw["capture"] or {}
        _warn_unknown("capture", {"debounce_s", "min_interval_s", "keepalive_min",
                                  "extract_workers", "extraction"}, cap)
        cfg.capture = CaptureConfig(
            debounce_s=float(_scalar("debounce_s", cap, cfg.capture.debounce_s)),
            min_interval_s=float(_scalar("min_interval_s", cap, cfg.capture.min_interval_s)),
            keepalive_min=float(_scalar("keepalive_min", cap, cfg.capture.keepalive_min)),
            extract_workers=int(_scalar("extract_workers", cap, cfg.capture.extract_workers)),
            extraction=_scalar("extraction", cap, cfg.capture.extraction),
        )
    if "scheduler" in raw:
        sch = raw["scheduler"] or {}
        _warn_unknown("scheduler", {"day_recap", "time_breakdown"}, sch)
        cfg.scheduler = SchedulerConfig(
            day_recap=_scalar("day_recap", sch, cfg.scheduler.day_recap),
            time_breakdown=_scalar("time_breakdown", sch, cfg.scheduler.time_breakdown),
        )
    if "rules" in raw:
        r = raw["rules"] or {}
        _warn_unknown("rules", {"window_class_category"}, r)
        wcc = r.get("window_class_category")
        if isinstance(wcc, dict):
            cfg.rules = {"window_class_category": wcc}
    if "observability" in raw:
        ob = raw["observability"] or {}
        _warn_unknown("observability", {"enabled"}, ob)
        cfg.observability = ObservabilityConfig(
            enabled=bool(_scalar("enabled", ob, cfg.observability.enabled))
        )
    return cfg
