"""Watched-range captions (v2 #38): the json3 slice rule, the disk cache, and
the daemon/DB wiring that lands cues_json + transcript on a closed session.

The slice rule is the issue's acceptance core: keep every cue the user heard
(overlapping either boundary), clamp the first kept cue's start and the last
kept cue's end to the watched range. Cached *content* is keyed by media_id so
a second session on the same video never re-fetches.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from heimdall.capture.captions import (CaptionCache, Cue, cues_json,
                                       cues_to_text, fetch_events,
                                       parse_json3, pick_track_url,
                                       slice_cues, slice_cues_to_ranges,
                                       watched_span_us)
from heimdall.capture.daemon import CaptureDaemon
from heimdall.capture.sessions import SessionTracker
from heimdall.config import Config
from heimdall.db import Database, init_db

FIXTURE = Path(__file__).parent / "data" / "events.json3"


def _fixture_events() -> list[dict]:
    return json.loads(FIXTURE.read_text())["events"]


def _cue(start_ms: int, end_ms: int, text: str) -> Cue:
    return Cue(start_ms=start_ms, end_ms=end_ms, text=text)


def _fake_info() -> dict:
    """yt-dlp metadata stub: one manual en json3 track (never fetched live)."""
    return {"subtitles": {"en": [{"ext": "json3", "url": "https://signed.invalid/tt"}]}}


# ---- parse + slice rule ----

def test_parse_json3_normalizes_events():
    cues = parse_json3(_fixture_events())
    assert len(cues) == 9
    assert cues[0] == _cue(0, 1680, "Never gonna give you up")
    assert cues[1] == _cue(1680, 3410, "Never gonna let you down")
    assert cues[7].text == "and hurt you"
    assert all(c.end_ms > c.start_ms for c in cues)


def test_parse_json3_falls_back_to_next_event_start():
    events = _fixture_events()[:2] + [
        {"tStartMs": 6000, "segs": [{"utf8": "no duration given"}]},
        {"tStartMs": 9000, "dDurationMs": 500, "segs": [{"utf8": "after"}]},
    ]
    cues = parse_json3(events)
    assert any(c.text == "no duration given" and c.end_ms == 9000 for c in cues)


def test_slice_cues_clamps_boundary_cues_to_watched_range():
    """Cues straddling the range edges are kept with clamped start/end; inner
    cues pass through untouched."""
    cues = [_cue(1000, 4000, "a"), _cue(4000, 7000, "b"),
            _cue(7000, 10000, "c"), _cue(10000, 13000, "d")]
    out = slice_cues(cues, 2000, 12000)
    assert out == [_cue(2000, 4000, "a"), _cue(4000, 7000, "b"),
                   _cue(7000, 10000, "c"), _cue(10000, 12000, "d")]


def test_slice_cues_single_overlapping_cue_clamps_both_ends():
    out = slice_cues([_cue(1000, 4000, "a")], 2000, 3000)
    assert out == [_cue(2000, 3000, "a")]


def test_slice_cues_keeps_no_non_overlapping_cues():
    cues = [_cue(0, 1000, "a"), _cue(1000, 2000, "b"), _cue(2000, 3000, "c")]
    assert slice_cues(cues, 1500, 2500) == [_cue(1500, 2000, "b"),
                                            _cue(2000, 2500, "c")]
    assert slice_cues(cues, 5000, 6000) == []
    assert slice_cues(cues, 0, 0) == []


def test_slice_cues_drops_degenerate_cues():
    out = slice_cues([_cue(0, 0, "ghost"), _cue(1000, 2000, "real")], 0, 2000)
    assert out == [_cue(0, 2000, "real")]


def test_slice_cues_on_fixture_json3_span():
    """End-to-end slice over the fixture: watch 3.41s..10.3s — the boundary
    cues are clamped, the rest fall in the middle."""
    events = _fixture_events()
    cues = parse_json3(events)
    out = slice_cues(cues, 3410, 10300)
    assert [c.text for c in out] == ["Never gonna run around", "and desert you",
                                     "Never gonna make you cry", "Never gonna say goodbye",
                                     "Never gonna tell a lie", "and hurt you"]
    assert out[0].start_ms == 3410 and out[-1].end_ms == 10300
    assert "Never gonna let you down" not in [c.text for c in out]


def test_cues_to_text_and_json_roundtrip():
    out = slice_cues(parse_json3(_fixture_events()), 0, 3410)
    assert cues_to_text(out) == "Never gonna give you up\nNever gonna let you down"
    parsed = json.loads(cues_json(out))
    assert parsed[0] == {"start_ms": 0, "end_ms": 1680,
                         "text": "Never gonna give you up"}


def test_watched_span_us_merges_seek_split_sub_ranges():
    assert watched_span_us([[900_000_000, 1_200_000_000], [3_000_000_000, 3_500_000_000]]) \
        == (900_000_000, 3_500_000_000)
    assert watched_span_us([[100, 200]]) == (100, 200)
    assert watched_span_us([]) is None
    assert watched_span_us([[100, 100]]) is None


def test_slice_cues_to_ranges_excludes_skipped_gap():
    """A seek-split session (0..3s then 6..9s) keeps no cues from the skipped
    3..6s gap: the transcript never stores what was not watched."""
    cues = [_cue(i * 1000, i * 1000 + 900, chr(ord("a") + i)) for i in range(10)]
    out = slice_cues_to_ranges(cues, [[0, 3000], [6000, 9000]])
    assert [c.text for c in out] == ["a", "b", "c", "g", "h", "i"]
    assert all(c.start_ms not in range(3000, 6000) for c in out)


def test_slice_cues_to_ranges_overlapping_ranges_dedupe():
    cues = [_cue(0, 2000, "a"), _cue(1000, 3000, "b")]
    out = slice_cues_to_ranges(cues, [[0, 2500], [1500, 3000]])
    assert len(out) == len({(c.start_ms, c.end_ms, c.text) for c in out})
    assert {c.text for c in out} == {"a", "b"}


# ---- track picking + clean failures ----

def _track_info(subtitles=None, auto=None):
    info = {}
    if subtitles:
        info["subtitles"] = subtitles
    if auto:
        info["automatic_captions"] = auto
    return info


def test_pick_track_prefers_manual_over_auto():
    info = _track_info(
        subtitles={"en": [{"ext": "json3", "url": "manual-url"}]},
        auto={"en": [{"ext": "json3", "url": "auto-url"}]},
    )
    assert pick_track_url(info) == "manual-url"


def test_pick_track_falls_back_to_auto_asr():
    info = _track_info(auto={"en": [{"ext": "json3", "url": "auto-url"}]})
    assert pick_track_url(info) == "auto-url"


def test_pick_track_prefers_json3_within_language():
    info = _track_info(auto={"en": [{"ext": "vtt", "url": "vtt-url"},
                                    {"ext": "json3", "url": "json3-url"}]})
    assert pick_track_url(info) == "json3-url"


def test_pick_track_returns_none_without_tracks():
    assert pick_track_url({}) is None
    assert pick_track_url(_track_info(auto={"en": []})) is None


def test_fetch_events_clean_failure_without_metadata(monkeypatch):
    monkeypatch.setattr("heimdall.capture.captions.extract_info",
                        lambda media_id, timeout=30: None)
    calls = []
    assert fetch_events("abc123", http_get=lambda url, timeout=0: calls.append(url)) is None
    assert calls == []  # never attempted a signed-track GET


def test_extract_info_returns_none_when_yt_dlp_fails(monkeypatch):
    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("age-gated")

    monkeypatch.setattr("yt_dlp.YoutubeDL", _Boom)
    assert fetch_events("dQw4w9WgXcQ") is None


# ---- disk cache ----

class _FakeGetter:
    """Records signed-track GETs so a cache hit provably skips the network."""

    def __init__(self, events):
        self.events = events
        self.calls = 0

    def __call__(self, url, *, timeout):
        self.calls += 1
        return json.dumps({"events": self.events})


def test_cache_stores_once_and_reuses(tmp_path, monkeypatch):
    monkeypatch.setattr("heimdall.capture.captions.extract_info",
                        lambda media_id, timeout=30: _fake_info())
    cache = CaptionCache(tmp_path / "captions")
    getter = _FakeGetter(_fixture_events())

    first = cache.slice_to("dQw4w9WgXcQ", 0, 3_410_000, http_get=getter)
    second = cache.slice_to("dQw4w9WgXcQ", 1_680_000, 5_200_000, http_get=getter)
    third = cache.slice_to("dQw4w9WgXcQ", 4_210_000, 10_300_000, http_get=getter)

    assert getter.calls == 1  # one network fetch, two cache hits
    assert first == [Cue(start_ms=0, end_ms=1680, text="Never gonna give you up"),
                     Cue(start_ms=1680, end_ms=3410, text="Never gonna let you down")]
    assert second[0].start_ms == 1680 and second[-1].end_ms == 5200
    assert third[0].start_ms == 4210 and third[-1].end_ms == 10300
    assert cache.path("dQw4w9WgXcQ").exists()


def test_cache_reuses_across_cache_instances(tmp_path, monkeypatch):
    monkeypatch.setattr("heimdall.capture.captions.extract_info",
                        lambda media_id, timeout=30: _fake_info())
    getter = _FakeGetter(_fixture_events())
    cache_dir = tmp_path / "captions"

    CaptionCache(cache_dir).slice_to("vid123", 0, 1_000_000, http_get=getter)
    got = CaptionCache(cache_dir).slice_to("vid123", 0, 1_000_000, http_get=getter)

    assert getter.calls == 1  # a fresh CaptionCache still finds the file
    assert got == [Cue(start_ms=0, end_ms=1000, text="Never gonna give you up")]


def test_cache_unavailable_events_returns_none_and_stores_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("heimdall.capture.captions.extract_info",
                        lambda media_id, timeout=30: None)
    cache = CaptionCache(tmp_path / "captions")
    assert cache.slice_to("gone", 0, 1_000_000) is None
    assert not cache.path("gone").exists()


# ---- daemon + DB wiring ----

def test_update_session_transcript_lands_on_row_and_fts(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    init_db(db.path)
    t = SessionTracker()
    t.play("chromium.instance1", title="Rick Astley - Never Gonna Give You Up",
           source="https://youtube.com/watch?v=dQw4w9WgXcQ", position_us=0,
           length_us=213_000_000, wall_ms=1_000)
    closed = t.stop("chromium.instance1", position_us=5_000_000, wall_ms=10_000)
    row_id = db.insert_watch_session(closed)
    db.update_session_transcript(row_id, cues_json='[{"start_ms":0}]',
                                 transcript="Never gonna give you up",
                                 transcript_source="captions")

    detail = db.get_watch_session(row_id)
    assert detail["cues_json"] == '[{"start_ms":0}]'
    assert detail["transcript"] == "Never gonna give you up"
    assert detail["transcript_source"] == "captions"

    total, items = db.search_watch_sessions("gonna give you up")
    assert total == 1
    assert items[0]["id"] == row_id


def _daemon(tmp_path: Path, tools) -> CaptureDaemon:
    daemon = CaptureDaemon(Config(data_dir=tmp_path), tools=tools)
    init_db(path=daemon.db_path)
    return daemon


class _FakeWatchTools:
    def __init__(self, transcript=None, resolve_media=True):
        self.players = ["chromium.instance1220"]
        self._transcript = transcript
        self.resolve_media = resolve_media
        self.calls = []

    def list_players(self) -> list[str]:
        return list(self.players)

    def playerctl_position(self, player: str):
        return None

    def cdp_resolve(self, window_title: str, position_us):
        if not self.resolve_media:
            return None
        return {"media_source": "https://youtube.com/watch?v=dQw4w9WgXcQ",
                "media_id": "dQw4w9WgXcQ"}

    def transcript_fetch(self, media_id: str, ranges: list):
        self.calls.append((media_id, ranges))
        return self._transcript


CHROMIUM_PLAY = "Playing||Rick Astley - Never Gonna Give You Up||chromium|0|213000000|"
CHROMIUM_STOP = "Stopped||||chromium|0|0|"


def test_daemon_attaches_transcript_to_chromium_session(tmp_path):
    tools = _FakeWatchTools({"cues_json": "[]",
                             "transcript": "Never gonna give you up"})
    daemon = _daemon(tmp_path, tools)
    daemon._on_track(CHROMIUM_PLAY)
    daemon._watch_poll_once()  # CDP/extension enrich sets media_id (#44)
    daemon._on_track(CHROMIUM_STOP)

    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["transcript"] == "Never gonna give you up"
    assert items[0]["cues_json"] == "[]"
    assert items[0]["transcript_source"] == "captions"
    assert tools.calls == [("dQw4w9WgXcQ", [])]  # degenerate segment dropped (#65)


def test_daemon_skips_transcript_without_media_id(tmp_path):
    tools = _FakeWatchTools({"cues_json": "[]", "transcript": "x"},
                            resolve_media=False)
    daemon = _daemon(tmp_path, tools)
    daemon._on_track(CHROMIUM_PLAY)
    daemon._watch_poll_once()  # resolution fails -> stays title-only
    daemon._on_track(CHROMIUM_STOP)

    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["media_id"] is None
    assert items[0]["transcript"] is None
    assert items[0]["cues_json"] is None
    assert tools.calls == []  # never attempted without a media_id (#38 scope)


def test_daemon_stays_title_only_on_transcript_failure(tmp_path):
    tools = _FakeWatchTools(None)  # fetch returned no transcript
    daemon = _daemon(tmp_path, tools)
    daemon._on_track(CHROMIUM_PLAY)
    daemon._watch_poll_once()
    daemon._on_track(CHROMIUM_STOP)

    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["transcript"] is None  # clean title-only session
    assert items[0]["cues_json"] is None
