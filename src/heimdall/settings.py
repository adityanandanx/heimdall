"""Live settings write-through: app edits config.yaml without owning it (#70).

The desktop app edits heimdall's own `config.yaml` — the one source of truth —
via dotted keys (`capture.ocr_engine: npu`). Unknown keys are preserved: we
round-trip the raw YAML, touching only the target path, so a hand-edited
section never gets clobbered by the app. After the write, a `settings.dirty`
marker is touched; the daemon and server poll it and re-read config live.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

DIRTY_FILE = "settings.dirty"

# The known writable surface. Keys outside this set are refused so a typo in
# the app can't silently corrupt config semantics (unknown YAML keys are still
# preserved on write, just not settable).
WRITABLE = {
    "capture.ocr_engine",
    "capture.extraction",
    "capture.change_gate",
    "capture.paused",
    "capture.window_class_merge",
    "watch.excluded_players",
    "watch.excluded_windows",
    "watch.media_resolver",
    "scheduler.day_recap",
    "scheduler.time_breakdown",
    "observability.enabled",
    "rules.window_class_category",
}

# Keys whose value may be null (None): a disabled scheduled pipe (#73) is the
# null exception to the spine's no-null rule.
NULLABLE = {
    "scheduler.day_recap",
    "scheduler.time_breakdown",
}


class UnknownSettingError(ValueError):
    """The dotted key is not a writable setting."""


def validate_key(key: str, value: Any) -> str | None:
    """Return an error message for an unwritable or malformed setting, else None.

    `value` may be any YAML-serialisable scalar/list/dict; only key membership
    and the immediate type of enforced enums are checked here (full semantic
    validation lives in config load, which the daemon runs on reload).
    """
    if key not in WRITABLE:
        return f"{key!r} is not a writable setting; writable keys: {sorted(WRITABLE)}"
    if value is None and key not in NULLABLE:
        return f"cannot write null for {key!r}"
    if value is None:
        return None
    if key == "capture.ocr_engine" and value not in ("cpu", "npu", "auto"):
        return f"capture.ocr_engine must be one of cpu|npu|auto, got {value!r}"
    if key == "capture.extraction" and value not in ("auto", "a11y", "ocr"):
        return f"capture.extraction must be one of auto|a11y|ocr, got {value!r}"
    if key in ("capture.change_gate", "capture.paused", "observability.enabled") and not isinstance(value, bool):
        return f"{key} must be a boolean, got {type(value).__name__}"
    if key == "watch.media_resolver" and value not in ("extension", "cdp"):
        return f"watch.media_resolver must be one of extension|cdp, got {value!r}"
    if key in ("watch.excluded_players", "watch.excluded_windows") and not isinstance(value, list):
        return f"{key} must be a list, got {type(value).__name__}"
    return None


def load_raw(config_path: Path) -> dict:
    """Raw YAML as a dict; unknown keys preserved untouched."""
    config_path = Path(config_path)
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return raw if isinstance(raw, dict) else {}


def get_value(config_path: Path, key: str) -> Any:
    """Read a dotted key from the raw config (or None)."""
    node: Any = load_raw(config_path)
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def apply_write(config_path: Path, key: str, value: Any, *, dirty_path: Path | None = None) -> None:
    """Set one dotted key in config.yaml, preserving everything else.

    Writes atomically (temp file + rename) so a crash mid-write never leaves a
    truncated config. If `dirty_path` is given (data_dir / settings.dirty), it
    is touched after the write so reloaders know to re-read.
    """
    if key not in WRITABLE:
        raise UnknownSettingError(f"{key!r} is not a writable setting")
    if value is None and key not in NULLABLE:
        raise ValueError(f"cannot write null for {key!r}")

    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    raw = load_raw(config_path)

    node = raw
    parts = key.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value

    fd, tmp = tempfile.mkstemp(dir=str(config_path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(raw, fh, sort_keys=False, allow_unicode=True)
        os.replace(tmp, config_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    if dirty_path is not None:
        touch_dirty(dirty_path)


def touch_dirty(dirty_path: Path) -> None:
    """Mark config as changed; reloaders re-read when mtime advances."""
    dirty_path = Path(dirty_path)
    dirty_path.parent.mkdir(parents=True, exist_ok=True)
    dirty_path.write_text("")


def dirty_since(dirty_path: Path, last_read: float) -> bool:
    """True when the dirty marker was touched after `last_read` (monotonic)."""
    try:
        return dirty_path.stat().st_mtime > last_read
    except OSError:
        return False
