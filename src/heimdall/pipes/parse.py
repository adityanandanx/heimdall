"""Parse + validation for structured pipe output (secondary test seam).

`parse` strips stray code fences before json.loads and validates the schema;
raises PipeValidationError on any malformed/structurally wrong output (the
upgrade-bar path records these).
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*|\s*```")


class PipeValidationError(ValueError):
    """Raised when the model's raw output is malformed or fails schema validation."""


def strip_fences(text: str) -> str:
    """Remove stray ```json ... ``` fences and surrounding whitespace."""
    return _FENCE.sub("", text).strip()


def parse_json_object(text: str, keys: tuple[str, ...] = ()) -> dict:
    """Find and parse the first JSON object in `text`.

    Tolerates a single top-level wrapper key (e.g. {"day_recap": {...}}) when
    `keys` are supplied and the wrapper itself lacks them.
    """
    stripped = strip_fences(text)
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            raise PipeValidationError("no JSON object in model output")
        try:
            obj = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise PipeValidationError(f"malformed JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise PipeValidationError("model output is not a JSON object")
    wrapped = [v for v in obj.values() if isinstance(v, dict)]
    if len(obj) == 1 and wrapped and keys and not all(k in obj for k in keys):
        obj = wrapped[0]
    return obj


def parse_recap(text: str) -> dict:
    keys = ("date", "summary", "accomplishments", "unfinished", "standout")
    obj = parse_json_object(text, keys)
    for key in keys:
        if key not in obj:
            raise PipeValidationError(f"recap missing key {key!r}")
    if not isinstance(obj["accomplishments"], list) or \
       not isinstance(obj["unfinished"], list) or \
       not isinstance(obj["standout"], list):
        raise PipeValidationError("recap list fields must be arrays")
    return {
        "date": str(obj["date"]),
        "summary": str(obj["summary"]),
        "accomplishments": [str(x) for x in obj["accomplishments"]],
        "unfinished": [str(x) for x in obj["unfinished"]],
        "standout": [str(x) for x in obj["standout"]],
    }


def parse_breakdown(text: str) -> dict:
    obj = parse_json_object(text, ("categories",))
    if "categories" not in obj or not isinstance(obj["categories"], list):
        raise PipeValidationError("breakdown missing categories array")
    categories = []
    for item in obj["categories"]:
        if not isinstance(item, dict) or "category" not in item or "minutes" not in item:
            raise PipeValidationError("breakdown category entry malformed")
        categories.append({
            "category": str(item["category"]),
            "minutes": int(item["minutes"]),
            "evidence": str(item.get("evidence", "")),
        })
    return {"categories": categories}
