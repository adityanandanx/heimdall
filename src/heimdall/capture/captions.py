"""YouTube caption fetch + watched-range slicing (v2 #38).

At session close the daemon turns a watched Chromium YouTube session into
searchable transcript text: fetch the video's caption track once per media_id
(manual captions preferred, auto/ASR fallback), cache the *content* on disk
under the data dir — signed `timedtext` URLs expire in ~7h, so URLs are never
cached — then slice the normalized cues to the watched video-time span with
the pure slicer and persist cues_json + transcript on the session row.

Everything here is fail-soft: an age-gated/removed/still-live/no-track video
or any network hiccup yields None, and the session stays title-only.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger("heimdall.captions")

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


@dataclass(frozen=True)
class Cue:
    """One normalized caption line: video-time ms + cleaned text."""

    start_ms: int
    end_ms: int
    text: str


def parse_json3(events: list[dict]) -> list[Cue]:
    """Normalize json3 `events` into `(start_ms, end_ms, text)` cues.

    json3 events carry `tStartMs` + `dDurationMs`; a trailing event missing a
    duration falls back to the next event's start. Text is the concat of the
    event's `segs[].utf8`, whitespace-normalized.
    """
    cues: list[Cue] = []
    for i, ev in enumerate(events):
        start = ev.get("tStartMs")
        if not isinstance(start, int):
            continue
        dur = ev.get("dDurationMs")
        if not isinstance(dur, int):
            nxt = events[i + 1].get("tStartMs") if i + 1 < len(events) else None
            dur = nxt - start if isinstance(nxt, int) else 0
        text = " ".join(
            (s.get("utf8") or "") for s in ev.get("segs") or [] if isinstance(s, dict)
        )
        text = " ".join(text.split())
        if not text:
            continue
        cues.append(Cue(start_ms=start, end_ms=start + max(dur, 0), text=text))
    return cues


def slice_cues(cues: list[Cue], start_ms: int, end_ms: int) -> list[Cue]:
    """Keep cues overlapping ``[start_ms, end_ms)`` and clamp the boundaries.

    A cue straddling either boundary is still speech the user heard, so it is
    kept; only the first kept cue's start and the last kept cue's end are
    clamped to the watched range. Zero/negative-duration cues are dropped.
    """
    kept = [c for c in cues
            if c.end_ms > c.start_ms and c.end_ms > start_ms and c.start_ms < end_ms]
    if not kept:
        return []
    first, last = kept[0], kept[-1]
    if len(kept) == 1:
        return [Cue(start_ms=start_ms, end_ms=end_ms, text=first.text)]
    out = [Cue(start_ms=start_ms, end_ms=first.end_ms, text=first.text)]
    out.extend(kept[1:-1])
    out.append(Cue(start_ms=last.start_ms, end_ms=end_ms, text=last.text))
    return out


def cues_to_text(cues: list[Cue]) -> str:
    """Denormalized plain text for FTS5: one cue per line."""
    return "\n".join(c.text for c in cues)


def watched_span_us(ranges: list[list[int]]) -> Optional[tuple[int, int]]:
    """Merged video-time span of the session's watched sub-ranges.

    The sub-ranges (split by seeks) merge into ``[min start, max end]`` — the
    whole span the user watched. None for an empty or degenerate span.
    """
    if not ranges:
        return None
    start = min(r[0] for r in ranges)
    end = max(r[1] for r in ranges)
    if end <= start:
        return None
    return start, end


def pick_track_url(info: dict) -> Optional[str]:
    """Signed json3 URL of the caption track: manual over auto, `en` first.

    ``subtitles`` are manual, ``automatic_captions`` are ASR. Within a
    language the json3 format is preferred (structured, ms-precision); any
    other format is a fallback. Returns None when the video has no track.
    """
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    for lang in ("en", "en-orig"):
        for source in (subs, auto):
            url = _json3_url(source.get(lang))
            if url:
                return url
    for tracks in (subs, auto):
        for lang in tracks:
            url = _json3_url(tracks[lang])
            if url:
                return url
    return None


def _json3_url(entries) -> Optional[str]:
    if not entries:
        return None
    for e in entries:
        if isinstance(e, dict) and e.get("ext") == "json3" and e.get("url"):
            return e["url"]
    for e in entries:
        if isinstance(e, dict) and e.get("url"):
            return e["url"]
    return None


def extract_info(media_id: str, *, timeout: float = 30) -> Optional[dict]:
    """yt-dlp metadata for one video id (its caption track lists + signed URLs).

    Runs the youtube extractor in-process with no download; returns None on
    any extraction failure (age-gated, removed, still-live, network).
    """
    try:
        import yt_dlp
    except ImportError:
        log.warning("yt-dlp not installed; no caption metadata")
        return None
    try:
        ydl = yt_dlp.YoutubeDL({
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": timeout,
        })
        return ydl.extract_info(f"https://www.youtube.com/watch?v={media_id}",
                                download=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("caption metadata for %s unavailable: %s", media_id,
                    type(exc).__name__)
        return None


def fetch_events(media_id: str, *, timeout: float = 30,
                 http_get=None) -> Optional[list[dict]]:
    """Caption track events for one video: signed-track GET, parsed to json3.

    ``http_get`` is injectable for tests; it maps a URL to the response text.
    Returns None on any failure, never raises.
    """
    info = extract_info(media_id, timeout=timeout)
    if not info:
        return None
    url = pick_track_url(info)
    if not url:
        log.warning("no caption track for %s", media_id)
        return None
    http_get = http_get or _http_get
    try:
        text = http_get(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        log.warning("caption fetch for %s failed: %s", media_id,
                    type(exc).__name__)
        return None
    try:
        events = json.loads(text).get("events")
    except (ValueError, AttributeError):
        return None
    return events if isinstance(events, list) else None


def _http_get(url: str, *, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


class CaptionCache:
    """One cached caption track per media_id on disk (content, never URLs).

    The cache dir holds one `{media_id}.json3` file per video so a later
    session on the same video re-slices without a network fetch; the signed
    URLs inside are dead on arrival and never persisted.
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)

    def path(self, media_id: str) -> Path:
        return self.cache_dir / f"{media_id}.json3"

    def load(self, media_id: str) -> Optional[list[dict]]:
        try:
            with open(self.path(media_id), encoding="utf-8") as fh:
                events = json.load(fh).get("events")
        except (OSError, ValueError, AttributeError):
            return None
        return events if isinstance(events, list) else None

    def store(self, media_id: str, events: list[dict]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path(media_id).with_suffix(".json3.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"events": events}, fh)
        os.replace(tmp, self.path(media_id))

    def events_for(self, media_id: str, *, timeout: float = 30,
                   http_get=None) -> Optional[list[dict]]:
        """Cached events, else fetched + cached. None when unavailable."""
        cached = self.load(media_id)
        if cached is not None:
            return cached
        events = fetch_events(media_id, timeout=timeout, http_get=http_get)
        if events:
            try:
                self.store(media_id, events)
            except OSError:
                log.warning("caption cache write failed for %s", media_id)
        return events

    def slice_to(self, media_id: str, start_us: int, end_us: int, *,
                 timeout: float = 30, http_get=None) -> Optional[list[Cue]]:
        """Cues of `media_id` sliced to the watched video-time range."""
        events = self.events_for(media_id, timeout=timeout, http_get=http_get)
        if not events:
            return None
        return slice_cues(parse_json3(events), start_us // 1000, end_us // 1000)


def cues_json(cues: list[Cue]) -> str:
    """The sliced cues as JSON for the session's `cues_json` column."""
    return json.dumps([asdict(c) for c in cues], ensure_ascii=False)
