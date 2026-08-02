"""Time helpers. DB stores UTC epoch ms; local-day boundaries are computed here.

The machine's local timezone defines "today" (UTC epoch ms in the DB, per #6).
"""

from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

UTC = _dt.timezone.utc


def local_tz() -> _dt.tzinfo:
    return _dt.datetime.now().astimezone().tzinfo


def _local_midnight(day: str) -> _dt.datetime:
    d = _dt.date.fromisoformat(day)
    return _dt.datetime.combine(d, _dt.time.min, tzinfo=local_tz())


def day_bounds(day: str) -> tuple[int, int]:
    """Local-day boundaries for `day` (YYYY-MM-DD) as UTC epoch ms, [start, end)."""
    start = _local_midnight(day).astimezone(UTC)
    end = start + _dt.timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def today_str() -> str:
    return _dt.datetime.now(local_tz()).strftime("%Y-%m-%d")


def parse_day(value: str | None) -> str:
    """Resolve today|yesterday|YYYY-MM-DD to a date string (default today)."""
    if not value:
        return today_str()
    now = _dt.datetime.now(local_tz())
    if value == "today":
        return now.strftime("%Y-%m-%d")
    if value == "yesterday":
        return (now - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
    return _dt.date.fromisoformat(value).isoformat()


def now_iso() -> str:
    return _dt.datetime.now(local_tz()).isoformat(timespec="seconds")


def ts_to_iso(ms: int) -> str:
    return _dt.datetime.fromtimestamp(ms / 1000, local_tz()).isoformat(timespec="seconds")


def iso_to_ms(value: str) -> int:
    """Parse an ISO-8601 timestamp (with or without offset) into UTC epoch ms."""
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = _dt.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz())
    return int(dt.astimezone(UTC).timestamp() * 1000)


def day_range_iso(day: str) -> str:
    start_ms, end_ms = day_bounds(day)
    return f"{ts_to_iso(start_ms)} - {ts_to_iso(end_ms - 1)}"


def fmt_ms(ms: int) -> str:
    """Local clock time HH:MM for a frame line."""
    return _dt.datetime.fromtimestamp(ms / 1000, local_tz()).strftime("%H:%M")
