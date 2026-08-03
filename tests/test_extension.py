"""Extension-backed Chromium media resolution (v2 #44).

The native-messaging extension streams ``{title, href, currentTimeUs}`` into
the ``media_stream`` table; this module title-matches it to the open MPRIS
session and reuses the CDP video-time alignment. Tests cover the pure match
decision, the db-backed resolver, the CaptureTools wiring (extension default,
CDP opt-in, no-db fail-soft), and the daemon poll that writes the resolution
into the session.
"""

from __future__ import annotations

import json
from pathlib import Path

from heimdall.capture import cdp
from heimdall.capture.daemon import CaptureDaemon, CaptureTools
from heimdall.capture.extension import ExtensionResolver, match_stream_rows
from heimdall.config import Config
from heimdall.db import init_db

YT_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
YT_ID = "dQw4w9WgXcQ"
FULL_TITLE = "Rick Astley - Never Gonna Give You Up (Official Video) - YouTube"
BARE_TITLE = "Rick Astley - Never Gonna Give You Up (Official Video)"
POS_US = 900_000_000
CHROME_LINE = f"Playing||{FULL_TITLE}||chromium|{POS_US}|7200000000|"


def _row(title=FULL_TITLE, href=YT_URL, current_time_us=POS_US, ts=1_000):
    return {"tab_title": title, "href": href, "current_time_us": current_time_us, "ts": ts}


# ---- pure match decision ----

def test_match_stream_rows_exact_title():
    got = match_stream_rows([_row()], FULL_TITLE, POS_US)
    assert got == {"media_source": YT_URL, "media_id": YT_ID, "current_us": POS_US}


def test_match_stream_rows_prefix_title_matches_bare_mpris():
    got = match_stream_rows([_row()], BARE_TITLE, POS_US)
    assert got["media_source"] == YT_URL
    assert got["media_id"] == YT_ID


def test_match_stream_rows_ignores_other_tabs():
    rows = [
        _row(title="Other tab", href="https://example.com/other"),
        _row(title="Another page", href="https://example.com/x"),
    ]
    assert match_stream_rows(rows, FULL_TITLE, POS_US) is None
    assert match_stream_rows(rows, BARE_TITLE, POS_US) is None


def test_match_stream_rows_multiple_tabs_only_matching_attributed():
    rows = [
        _row(title="Other tab", href="https://example.com/other"),
        _row(),
        _row(title="Other tab", href="https://example.com/x"),
    ]
    got = match_stream_rows(rows, BARE_TITLE, POS_US)
    assert got["media_source"] == YT_URL
    assert got["media_id"] == YT_ID


def test_match_stream_rows_aligns_video_time_among_duplicates():
    rows = [
        _row(current_time_us=POS_US + 90_000_000, ts=2_000),  # misaligned duplicate
        _row(current_time_us=POS_US, ts=1_000),               # aligned
    ]
    got = match_stream_rows(rows, FULL_TITLE, POS_US)
    assert got["current_us"] == POS_US


def test_match_stream_rows_unknown_position_never_blocks():
    got = match_stream_rows([_row(current_time_us=None)], FULL_TITLE, None)
    assert got["media_source"] == YT_URL
    assert match_stream_rows([_row()], FULL_TITLE, None)["media_id"] == YT_ID


def test_match_stream_rows_empty():
    assert match_stream_rows([], FULL_TITLE, POS_US) is None


def test_match_stream_rows_extracts_shorts_and_short_url_ids():
    cases = [
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ]
    for href, vid in cases:
        got = match_stream_rows([_row(href=href)], FULL_TITLE, POS_US)
        assert got["media_source"] == href
        assert got["media_id"] == vid


# ---- db-backed resolver ----

class _StreamDB:
    def __init__(self, rows):
        self._rows = rows

    def latest_media_stream(self):
        return self._rows


def test_resolver_reads_stream(db):
    db.upsert_media_stream(href=YT_URL, tab_title=FULL_TITLE,
                           current_time_us=POS_US, ts=1_000)
    got = ExtensionResolver(db).resolve(BARE_TITLE, POS_US)
    assert got == {"media_source": YT_URL, "media_id": YT_ID, "current_us": POS_US}
    rows = db.latest_media_stream()
    assert len(rows) == 1
    assert rows[0]["href"] == YT_URL
    assert rows[0]["tab_title"] == FULL_TITLE


def test_resolver_upsert_keyed_by_href(db):
    db.upsert_media_stream(href=YT_URL, tab_title="Old title",
                           current_time_us=1, ts=1_000)
    db.upsert_media_stream(href=YT_URL, tab_title=FULL_TITLE,
                           current_time_us=POS_US, ts=2_000)
    db.upsert_media_stream(href="https://example.com/other", tab_title="Other",
                           current_time_us=0, ts=3_000)
    rows = db.latest_media_stream()
    assert len(rows) == 2  # two distinct tabs
    assert {r["tab_title"] for r in rows} == {FULL_TITLE, "Other"}


def test_resolver_empty_stream_is_none(db):
    assert ExtensionResolver(db).resolve(BARE_TITLE, POS_US) is None


def test_resolver_db_error_is_none():
    class Boom:
        def latest_media_stream(self):
            raise RuntimeError("db locked")

    assert ExtensionResolver(Boom()).resolve(BARE_TITLE, POS_US) is None


# ---- CaptureTools wiring (#44) ----

def test_capture_tools_extension_default_wires_extension_resolver(db):
    tools = CaptureTools(media_resolver="extension", db=db)
    db.upsert_media_stream(href=YT_URL, tab_title=FULL_TITLE,
                           current_time_us=POS_US, ts=1_000)
    assert tools.cdp_resolve(BARE_TITLE, POS_US)["media_id"] == YT_ID


def test_capture_tools_extension_without_db_fails_soft():
    tools = CaptureTools(media_resolver="extension", db=None)
    assert tools.cdp_resolve(BARE_TITLE, POS_US) is None


def test_capture_tools_cdp_resolver_is_opt_in():
    tools = CaptureTools(media_resolver="cdp")
    assert tools.cdp_resolve == tools._cdp_resolve


def test_capture_tools_default_is_extension():
    tools = CaptureTools()
    assert tools.cdp_resolve == tools._extension_resolve


# ---- daemon poll wiring (mirrors test_cdp) ----

class _FakeWatchTools:
    def __init__(self, players=None, position=None, cdp_resolve=None):
        self.players = list(players or [])
        self._position = position
        self.cdp_resolve = cdp_resolve

    def list_players(self) -> list[str]:
        return list(self.players)

    def playerctl_position(self, player):
        return self._position


def _daemon(tmp_path: Path, tools) -> CaptureDaemon:
    daemon = CaptureDaemon(Config(data_dir=tmp_path), tools=tools)
    init_db(path=daemon.db_path)
    return daemon


def test_watch_poll_enriches_chromium_session_from_extension_stream(tmp_path):
    """A poll tick resolves the exact URL + video id from the extension stream
    and the closed session keeps them (#44)."""
    daemon = _daemon(tmp_path, _FakeWatchTools(
        players=["chromium.instance1220"], position=POS_US))
    daemon.tools.cdp_resolve = ExtensionResolver(daemon.db).resolve
    daemon._on_track(CHROME_LINE)
    daemon.db.upsert_media_stream(href=YT_URL, tab_title=FULL_TITLE,
                                  current_time_us=POS_US, ts=1_000)

    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["media_source"] is None  # MPRIS carries no URL for Chromium

    daemon._watch_poll_once()

    item = daemon.db.get_watch_session(items[0]["id"])
    assert item["media_source"] == YT_URL
    assert item["media_id"] == YT_ID
    assert item["live"] == 1


def test_watch_poll_extension_stream_empty_keeps_title_only(tmp_path):
    """An empty stream leaves the session title-only and never crashes (#44)."""
    daemon = _daemon(tmp_path, _FakeWatchTools(
        players=["chromium.instance1220"], position=POS_US))
    daemon.tools.cdp_resolve = ExtensionResolver(daemon.db).resolve
    daemon._on_track(CHROME_LINE)
    daemon._watch_poll_once()

    _, items = daemon.db.list_watch_sessions()
    assert items[0]["media_source"] is None
    assert items[0]["media_id"] is None
