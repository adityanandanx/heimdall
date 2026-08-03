"""CDP resolution for Chromium watch-sessions (v2 #36).

Chromium exposes no MPRIS URL, so the exact YouTube URL + video id come from
the DevTools protocol: read the browser WebSocket endpoint from the profile's
DevToolsActivePort, list targets, match the page whose title equals the MPRIS
window title, then evaluate `location.href` + `video.currentTime` in that page.
The video-time double-check (CDP seconds vs the MPRIS µs position, same epoch
semantics as pos_start/pos_end) picks the right tab among title duplicates and
refuses to attach a wrong id.

Everything sits behind an injectable transport (`connect`/`get_targets`/
`evaluate`) so the pure decisions are unit-tested and the daemon can run CDP
fail-soft: any missing file, unreachable port, or evaluation error degrades to
title-only with no crash.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

DEFAULT_PROFILE_DIRS = ("google-chrome", "chromium")
DEVTOOLS_ACTIVE_PORT = "DevToolsActivePort"
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
ALIGN_TOLERANCE_US = 60_000_000  # 60s: MPRIS position can lag a few seconds
_EVAL_EXPRESSION = (
    "({href: location.href, "
    "current: document.querySelector('video')?.currentTime ?? null})"
)


def parse_active_port(text: str) -> Optional[tuple[int, str]]:
    """``\"9222\\n/devtools/browser/<uuid>\"`` -> ``(port, ws_path)``.

    Returns None for malformed content (no port, a non-numeric port, or a
    path that is not a DevTools endpoint) so a corrupt file degrades cleanly.
    """
    lines = text.strip().splitlines()
    if len(lines) < 2:
        return None
    try:
        port = int(lines[0].strip())
    except ValueError:
        return None
    path = lines[1].strip()
    if not path.startswith("/devtools/") or not 0 < port < 65536:
        return None
    return port, path


def video_id_from_url(url: str) -> Optional[str]:
    """YouTube video id from a watch/shorts/embed/live/youtu.be URL."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.netloc or "").lower()
    if host == "youtu.be":
        vid = parsed.path.strip("/")
    elif host.endswith("youtube.com"):
        if parsed.path in ("/watch", "/watch/"):
            vid = parse_qs(parsed.query).get("v", [None])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            vid = parsed.path.rsplit("/", 1)[-1]
        else:
            vid = None
    else:
        return None
    if vid and _VIDEO_ID_RE.fullmatch(vid):
        return vid
    return None


def is_youtube_url(url: str) -> bool:
    """True for any host we can pull a video id from."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.netloc or "").lower()
    return host == "youtu.be" or host.endswith("youtube.com")


def pick_page_targets(targets: list[dict], window_title: str) -> list[dict]:
    """Page targets whose title matches the MPRIS window title, YouTube watch
    pages first (a second tab can share the title)."""
    pages = [t for t in targets if (t.get("type") or "").lower() == "page"]
    matches = [t for t in pages if (t.get("title") or "") == window_title]
    return sorted(
        matches,
        key=lambda t: 0 if is_youtube_url(t.get("url") or "") else 1,
    )


def current_us(seconds) -> Optional[int]:
    """``video.currentTime`` seconds -> video-time microseconds, matching the
    MPRIS `{{position}}` epoch used across the watch-session pipeline."""
    if seconds is None:
        return None
    return int(round(float(seconds) * 1_000_000))


def aligned(mpris_us: Optional[int], video_us: Optional[int],
            tolerance_us: int = ALIGN_TOLERANCE_US) -> bool:
    """True when the CDP video-time matches the MPRIS position within tolerance
    (or when either side is unknown, so a missing position never blocks)."""
    if mpris_us is None or video_us is None:
        return True
    return abs(mpris_us - video_us) <= tolerance_us


def read_browser_ws_url(profile_dir) -> Optional[str]:
    """The browser WebSocket endpoint from a profile's DevToolsActivePort."""
    try:
        text = (Path(profile_dir) / DEVTOOLS_ACTIVE_PORT).read_text()
    except OSError:
        return None
    parsed = parse_active_port(text)
    if parsed is None:
        return None
    port, path = parsed
    return f"ws://127.0.0.1:{port}{path}"


# ---- injectable transport ----

_IDS = itertools.count(1)


def _rpc(ws, method: str, params=None, session_id: Optional[str] = None,
         timeout: float = 3.0) -> dict:
    """One request/response exchange, ignoring browser events in between."""
    rid = next(_IDS)
    body = {"id": rid, "method": method, "params": params or {}}
    if session_id is not None:
        body["sessionId"] = session_id
    ws.send(json.dumps(body))
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"CDP {method} timed out")
        msg = json.loads(ws.recv(timeout=remaining))
        if msg.get("id") == rid:
            return msg


def _connect(url: str, timeout: float):
    from websockets.sync.client import connect

    return connect(url, open_timeout=timeout)


def _get_targets(ws) -> list[dict]:
    return _rpc(ws, "Target.getTargets")["result"]["targetInfos"]


def _evaluate(ws, target_id: str, expression: str, timeout: float):
    """Evaluate `expression` in the page: attach (flattened session), then
    Runtime.evaluate with the session id on the browser WebSocket."""
    attached = _rpc(
        ws, "Target.attachToTarget",
        {"targetId": target_id, "flatten": True}, timeout=timeout,
    )
    session_id = attached["result"]["sessionId"]
    resp = _rpc(
        ws, "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
        session_id=session_id, timeout=timeout,
    )
    result = resp.get("result", {})
    if result.get("exceptionDetails"):
        raise RuntimeError("page evaluation failed")
    return result.get("result", {}).get("value")


def resolve_media(ws_url: str, window_title: str, *,
                  mpris_pos_us: Optional[int] = None,
                  connect: Optional[Callable] = None,
                  get_targets: Optional[Callable] = None,
                  evaluate: Optional[Callable] = None,
                  timeout: float = 2.0,
                  tolerance_us: int = ALIGN_TOLERANCE_US) -> Optional[dict]:
    """Resolve ``{media_source, media_id, current_us}`` for the window, or
    None when CDP is unreachable / no tab matches / nothing aligns.

    Candidates whose `video.currentTime` is far from the MPRIS position are
    skipped, so a duplicate tab playing something else is never misattributed.
    """
    if connect is None or get_targets is None or evaluate is None:
        return None
    ws = None
    try:
        ws = connect(ws_url, timeout)
        targets = get_targets(ws)
    except Exception:  # noqa: BLE001
        return None
    try:
        for target in pick_page_targets(targets, window_title):
            try:
                page = evaluate(ws, target["targetId"], _EVAL_EXPRESSION, timeout)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(page, dict) or not page.get("href"):
                continue
            video_us = current_us(page.get("current"))
            if not aligned(mpris_pos_us, video_us, tolerance_us):
                continue
            href = page["href"]
            return {
                "media_source": href,
                "media_id": video_id_from_url(href),
                "current_us": video_us,
            }
        return None
    except Exception:  # noqa: BLE001
        return None
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass


def resolve_chromium_media(*, window_title: str,
                           position_us: Optional[int] = None,
                           config_root: Optional[Path] = None,
                           profile_dirs=DEFAULT_PROFILE_DIRS,
                           connect: Optional[Callable] = None,
                           get_targets: Optional[Callable] = None,
                           evaluate: Optional[Callable] = None,
                           timeout: float = 2.0,
                           tolerance_us: int = ALIGN_TOLERANCE_US) -> Optional[dict]:
    """Resolve the media for a Chromium watch-session from DevToolsActivePort.

    Tries each profile dir under the config root (``~/.config`` by default)
    until one yields a match; any failure across all of them returns None.
    """
    root = Path(config_root) if config_root is not None else (
        Path(os.path.expanduser("~")) / ".config"
    )
    for name in profile_dirs:
        ws_url = read_browser_ws_url(root / name)
        if ws_url is None:
            continue
        resolved = resolve_media(
            ws_url, window_title,
            mpris_pos_us=position_us,
            connect=connect or _connect,
            get_targets=get_targets or _get_targets,
            evaluate=evaluate or _evaluate,
            timeout=timeout, tolerance_us=tolerance_us,
        )
        if resolved is not None:
            return resolved
    return None
