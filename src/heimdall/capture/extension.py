"""Extension-backed media resolution for Chromium watch-sessions (v2 #44).

A native-messaging MV3 extension streams each YouTube tab's
``document.title`` + ``location.href`` + ``video.currentTime`` into the API,
which lands in the ``media_stream`` table. The resolver replaces CDP as the
default source of truth: it title-matches the open session's MPRIS window
title against the streamed rows (exact, then ``... - YouTube`` prefix — the
MPRIS title may be bare), then the video-time check reuses the CDP alignment
so a duplicate tab playing something else is never misattributed.

Same seam as CDP: ``resolve`` returns ``{media_source, media_id, current_us}``
or None, so an empty stream, a title mismatch, or a dead DB degrades to a
title-only session with no crash.
"""

from __future__ import annotations

from typing import Optional

from heimdall.capture.cdp import ALIGN_TOLERANCE_US, aligned, pick_page_targets, video_id_from_url


def match_stream_rows(rows: list[dict], window_title: str,
                      position_us: Optional[int] = None,
                      tolerance_us: int = ALIGN_TOLERANCE_US) -> Optional[dict]:
    """Pick the streamed tab that matches the MPRIS title and video position.

    `rows` are the ``media_stream`` readings (tab_title/href/current_time_us/ts),
    newest sighting first. Only a tab whose title matches the window is
    considered; among matches the most recent is tried first, and the video
    time must sit within tolerance of the MPRIS position (or either side is
    unknown). Returns ``{media_source, media_id, current_us}`` or None.
    """
    targets = [
        {
            "type": "page",
            "title": r["tab_title"],
            "url": r["href"],
            "current_time_us": r.get("current_time_us"),
        }
        for r in rows
    ]
    for target in pick_page_targets(targets, window_title):
        video_us = target["current_time_us"]
        if not aligned(position_us, video_us, tolerance_us):
            continue
        href = target["url"]
        return {
            "media_source": href,
            "media_id": video_id_from_url(href),
            "current_us": video_us,
        }
    return None


class ExtensionResolver:
    """Title-matches an open watch-session against the extension stream."""

    def __init__(self, db, *, tolerance_us: int = ALIGN_TOLERANCE_US):
        self._db = db
        self._tolerance_us = tolerance_us

    def resolve(self, window_title: str,
                position_us: Optional[int] = None) -> Optional[dict]:
        try:
            rows = self._db.latest_media_stream()
        except Exception:  # noqa: BLE001
            return None
        if not rows:
            return None
        return match_stream_rows(rows, window_title, position_us,
                                 tolerance_us=self._tolerance_us)
