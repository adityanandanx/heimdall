"""Pure event/trigger/debounce logic for the capture daemon (secondary seam).

socket2/grim/hyprctl/playerctl stay behind interfaces in daemon.py and are not
tested; this module holds the testable decision logic.
"""

from __future__ import annotations

# socket2 event name -> canonical trigger. v2 variants carry no extra metadata
# but still signal a change. Events like screencast (grim's own capture),
# closewindow, focusedmon etc. are not capture triggers.
_TRIGGER_MAP = {
    "activewindow": "activewindow",
    "activewindowv2": "activewindow",
    "openwindow": "openwindow",
    "workspace": "workspace",
    "workspacev2": "workspace",
    "fullscreen": "fullscreen",
    "windowtitle": "windowtitle",
    "windowtitlev2": "windowtitle",
}

EXCLUDED_EVENTS = ("screencast", "closewindow", "focusedmon", "movewindow", "monitoradded")


def parse_socket2_line(line: str) -> dict | None:
    """Split a socket2 line into {type, payload}; None if not an event line."""
    line = line.strip()
    if not line or ">>" not in line:
        return None
    kind, payload = line.split(">>", 1)
    return {"type": kind, "payload": payload}


def classify_trigger(kind: str) -> str | None:
    """Map a socket2 event name to a capture trigger, or None to ignore it."""
    return _TRIGGER_MAP.get(kind)


def debounce_burst(events: list[tuple[float, str]], debounce_s: float) -> list[tuple[float, str, float]]:
    """Collapse a burst of events into one fire per quiet gap.

    Events are (arrival_ts, trigger). A new burst starts when the gap between
    consecutive events exceeds `debounce_s`. Returns
    [(burst_start_ts, trigger, fire_at)] — one fire per burst, carrying the
    last event's trigger and firing `debounce_s` after the last event.
    """
    ordered = sorted(events)
    fires: list[tuple[float, str, float]] = []
    burst: list[tuple[float, str]] = []
    for ev in ordered:
        if burst and ev[0] - burst[-1][0] > debounce_s:
            fires.append((burst[0][0], burst[-1][1], burst[-1][0] + debounce_s))
            burst = []
        burst.append(ev)
    if burst:
        fires.append((burst[0][0], burst[-1][1], burst[-1][0] + debounce_s))
    return fires


def should_capture(now: float, last_fire: float, min_interval_s: float) -> bool:
    """Min-interval throttle: at least `min_interval_s` between captures."""
    return now - last_fire >= min_interval_s


def is_duplicate(signature: tuple | None, last_signature: tuple | None) -> bool:
    """Skip a frame whose window signature is unchanged (title-delta dedupe)."""
    return signature is not None and signature == last_signature


def is_track_change(last_track: tuple | None, player: str, artist: str, title: str) -> bool:
    """True when an MPRIS metadata line is a different track than the last one
    seen — a mid-play track switch, which is a capture trigger (#5)."""
    return (player, artist or "", title or "") != last_track


def workspace_id(meta: dict) -> int | None:
    """hyprctl activewindow's `workspace` is a dict {id, name}; return the id."""
    ws = meta.get("workspace") or {}
    try:
        return int(ws["id"])
    except (KeyError, TypeError, ValueError):
        return None


def activewindow_signature(meta: dict) -> tuple:
    """Metadata that defines 'the same window' for dedupe."""
    ws = meta.get("workspace") or {}
    return (
        meta.get("class"),
        meta.get("title"),
        f"{ws.get('id')}:{ws.get('name')}",
    )
