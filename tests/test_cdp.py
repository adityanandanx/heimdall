"""CDP resolution for Chromium watch-sessions (v2 #36): DevToolsActivePort
parsing, YouTube id extraction, page-title matching across tabs, video-time
alignment, clean degradation when CDP is unreachable, and the daemon poll
wiring that writes media_source/media_id into the session."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from heimdall.capture import cdp
from heimdall.capture.daemon import CaptureDaemon
from heimdall.config import Config
from heimdall.db import init_db

YT_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
YT_ID = "dQw4w9WgXcQ"
TITLE = "Rick Astley - Never Gonna Give You Up (Official Video) - YouTube"
CHROME_LINE = f"Playing||{TITLE}||chromium|900000000|7200000000|"
STOPPED_CHROME = "Stopped||||chromium|0|0|"

PAGE_A = {"targetId": "TARGET_A", "type": "page", "title": TITLE,
          "url": YT_URL}
PAGE_B = {"targetId": "TARGET_B", "type": "page", "title": "Other tab",
          "url": "https://example.com/other"}


def _page(**kw):
    base = {"targetId": "X", "type": "page", "title": "", "url": ""}
    base.update(kw)
    return base


def _fake_transport(targets, evaluations, raises=None):
    """Injectables for resolve_media; `evaluations` maps targetId -> value."""

    def connect(url, timeout):
        if raises is not None:
            raise raises
        return object()

    def get_targets(ws):
        return targets

    def evaluate(ws, target_id, expression, timeout):
        return evaluations[target_id]

    return connect, get_targets, evaluate


class _CountingTransport:
    """Track how many times the browser WebSocket is opened."""

    def __init__(self, targets, evaluations, fail_first_targets=False):
        self.targets = targets
        self.evaluations = evaluations
        self.fail_first_targets = fail_first_targets
        self.connect_count = 0
        self.targets_calls = 0

    def connect(self, url, timeout):
        self.connect_count += 1
        return object()

    def get_targets(self, ws):
        self.targets_calls += 1
        if self.fail_first_targets and self.connect_count == 1:
            raise ConnectionError("browser closed")
        return self.targets

    def evaluate(self, ws, target_id, expression, timeout):
        return self.evaluations[target_id]


# ---- persistent session (Chrome 136+ approval prompt per connection) ----

def test_cdp_session_reuses_socket_across_polls():
    """One WebSocket is opened and reused: no-match polls do not reopen, so
    Chrome's "Allow remote debugging?" approval appears once per browser."""
    transport = _CountingTransport([PAGE_B], {})
    session = cdp.CdpSession(
        connect=transport.connect, get_targets=transport.get_targets,
        evaluate=transport.evaluate)
    for _ in range(3):
        assert session.resolve("ws://x", TITLE) is None
    assert transport.connect_count == 1
    assert transport.targets_calls == 3


def test_cdp_session_reconnects_when_socket_dies():
    """A dead socket is dropped and the next poll opens a fresh one."""
    transport = _CountingTransport([PAGE_A], {"TARGET_A": {"href": YT_URL, "current": 900.0}},
                                   fail_first_targets=True)
    session = cdp.CdpSession(
        connect=transport.connect, get_targets=transport.get_targets,
        evaluate=transport.evaluate)
    assert session.resolve("ws://x", TITLE) is None   # dead -> None, closed
    resolved = session.resolve("ws://x", TITLE)       # reconnects -> resolves
    assert resolved == {"media_source": YT_URL, "media_id": YT_ID,
                        "current_us": 900_000_000}
    assert transport.connect_count == 2


def test_cdp_session_reconnects_when_url_changes():
    """A new browser (new DevToolsActivePort) gets a new connection."""
    transport = _CountingTransport([PAGE_B], {})
    session = cdp.CdpSession(
        connect=transport.connect, get_targets=transport.get_targets,
        evaluate=transport.evaluate)
    assert session.resolve("ws://old", TITLE) is None
    assert session.resolve("ws://new", TITLE) is None
    assert transport.connect_count == 2


# ---- DevToolsActivePort parsing ----

def test_parse_active_port():
    assert cdp.parse_active_port("9222\n/devtools/browser/abc-def\n") == (
        9222, "/devtools/browser/abc-def")


def test_parse_active_port_malformed_returns_none():
    assert cdp.parse_active_port("") is None
    assert cdp.parse_active_port("9222") is None  # no ws path
    assert cdp.parse_active_port("abc\n/devtools/browser/x") is None
    assert cdp.parse_active_port("9222\n/not-a-devtools-path") is None
    assert cdp.parse_active_port("0\n/devtools/browser/x") is None


# ---- YouTube id extraction ----

def test_video_id_from_url_extracts_watch_forms():
    assert cdp.video_id_from_url(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ") == YT_ID
    assert cdp.video_id_from_url(
        "https://youtu.be/dQw4w9WgXcQ") == YT_ID
    assert cdp.video_id_from_url(
        "https://www.youtube.com/shorts/dQw4w9WgXcQ") == YT_ID
    assert cdp.video_id_from_url(
        "https://www.youtube.com/embed/dQw4w9WgXcQ") == YT_ID
    assert cdp.video_id_from_url(
        "https://www.youtube.com/live/dQw4w9WgXcQ") == YT_ID
    assert cdp.video_id_from_url(
        "https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s") == YT_ID


def test_video_id_from_url_rejects_non_youtube():
    assert cdp.video_id_from_url("https://example.com/watch?v=dQw4w9WgXcQ") is None
    assert cdp.video_id_from_url("https://www.youtube.com/") is None
    assert cdp.video_id_from_url("https://www.youtube.com/watch?t=42s") is None
    assert cdp.video_id_from_url("https://youtu.be/too-short-id") is None


# ---- page-title matching ----

def test_pick_page_targets_matches_window_title():
    targets = [PAGE_B, PAGE_A, {"targetId": "W", "type": "service_worker",
                                "title": TITLE, "url": YT_URL}]
    picked = cdp.pick_page_targets(targets, TITLE)
    assert picked == [PAGE_A]  # service workers are never page candidates


def test_pick_page_targets_prefix_matches_site_suffix():
    """Chrome's MPRIS title is the bare media title; the CDP page title carries
    the ` - YouTube` suffix, so a prefix match is the fallback."""
    bare = "LIVE: The /wayfinder Demo"
    yt = _page(title=f"{bare} - YouTube", url=YT_URL)
    clip = _page(title=f"{bare} clip", url="https://example.com/clip")
    other = _page(title="Something else", url="https://example.com/x")
    picked = cdp.pick_page_targets([clip, other, yt], bare)
    assert picked == [yt, clip]  # both prefix; youtube watch pages first


def test_pick_page_targets_exact_wins_over_prefix():
    """An exact title match outranks prefix matches from other tabs."""
    exact = _page(title=TITLE, url=YT_URL)
    prefixed = _page(title=f"{TITLE} (extra)", url=YT_URL)
    assert cdp.pick_page_targets([prefixed, exact], TITLE) == [exact, prefixed]


def test_pick_page_targets_empty_title_matches_nothing():
    assert cdp.pick_page_targets([PAGE_A], "") == []


def test_pick_page_targets_prefers_youtube_watch():
    other = _page(title=TITLE, url="https://example.com/stream")
    targets = [other, PAGE_A]
    assert cdp.pick_page_targets(targets, TITLE) == [PAGE_A, other]


def test_pick_page_targets_no_match_returns_empty():
    assert cdp.pick_page_targets([PAGE_A], "Completely different window") == []


# ---- video-time alignment ----

def test_current_us_converts_seconds():
    assert cdp.current_us(900.0) == 900_000_000
    assert cdp.current_us(1519.724521) == 1_519_724_521
    assert cdp.current_us(None) is None


def test_aligned_within_tolerance():
    assert cdp.aligned(900_000_000, 900_000_000)
    assert cdp.aligned(900_000_000, 960_000_000)  # within 60s
    assert not cdp.aligned(900_000_000, 1_200_000_000)
    assert cdp.aligned(None, 1_200_000_000)  # unknown side never blocks
    assert cdp.aligned(900_000_000, None)


# ---- resolver with fake transport ----

def test_resolve_media_returns_url_and_id():
    connect, get_targets, evaluate = _fake_transport(
        [PAGE_B, PAGE_A],
        {"TARGET_A": {"href": YT_URL, "current": 900.0}},
    )
    resolved = cdp.resolve_media(
        "ws://127.0.0.1:9222/devtools/browser/x", TITLE,
        mpris_pos_us=900_000_000, connect=connect,
        get_targets=get_targets, evaluate=evaluate,
    )
    assert resolved == {"media_source": YT_URL, "media_id": YT_ID,
                        "current_us": 900_000_000}


def test_resolve_media_prefix_title_resolves():
    """The MPRIS bare title matches a page whose CDP title carries the site
    suffix; the position double-check confirms the right tab."""
    bare = "LIVE: The /wayfinder Demo"
    page = _page(targetId="LIVE_TAB", title=f"{bare} - YouTube", url=YT_URL)
    connect, get_targets, evaluate = _fake_transport(
        [page], {"LIVE_TAB": {"href": YT_URL, "current": 1519.724514}})
    resolved = cdp.resolve_media(
        "ws://x", bare, mpris_pos_us=1_519_724_521,
        connect=connect, get_targets=get_targets, evaluate=evaluate,
    )
    assert resolved["media_source"] == YT_URL
    assert resolved["media_id"] == YT_ID
    assert resolved["current_us"] == 1_519_724_514


def test_resolve_media_skips_misaligned_tab_for_matching_one():
    """Two tabs with the same title: the one whose video-time matches the MPRIS
    position wins; the other is never misattributed."""
    dup_a = _page(targetId="DUP_A", title=TITLE,
                  url="https://www.youtube.com/watch?v=AAAA1AAAAAA")
    dup_b = _page(targetId="DUP_B", title=TITLE, url=YT_URL)
    connect, get_targets, evaluate = _fake_transport(
        [dup_a, dup_b],
        {"DUP_A": {"href": dup_a["url"], "current": 10.0},
         "DUP_B": {"href": YT_URL, "current": 900.0}},
    )
    resolved = cdp.resolve_media(
        "ws://x", TITLE, mpris_pos_us=900_000_000,
        connect=connect, get_targets=get_targets, evaluate=evaluate,
    )
    assert resolved["media_source"] == YT_URL
    assert resolved["media_id"] == YT_ID


def test_resolve_media_unreachable_returns_none():
    connect, get_targets, evaluate = _fake_transport(
        [], {}, raises=ConnectionRefusedError)
    assert cdp.resolve_media(
        "ws://x", TITLE, connect=connect, get_targets=get_targets,
        evaluate=evaluate) is None


def test_resolve_media_eval_failure_returns_none():
    connect, get_targets, evaluate = _fake_transport(
        [PAGE_A], {})

    def bad_eval(ws, target_id, expression, timeout):
        raise RuntimeError("page evaluation failed")

    assert cdp.resolve_media(
        "ws://x", TITLE, connect=connect, get_targets=get_targets,
        evaluate=bad_eval) is None


def test_resolve_media_no_title_match_returns_none():
    connect, get_targets, evaluate = _fake_transport(
        [PAGE_A], {"TARGET_A": {"href": YT_URL, "current": 900.0}})
    assert cdp.resolve_media(
        "ws://x", "Unrelated window", connect=connect,
        get_targets=get_targets, evaluate=evaluate) is None


# ---- profile-driven resolution ----

def test_resolve_chromium_media_reads_profile_and_resolves(tmp_path):
    profile = tmp_path / "google-chrome"
    profile.mkdir(parents=True)
    (profile / "DevToolsActivePort").write_text(
        "9333\n/devtools/browser/uuid\n")
    connect, get_targets, evaluate = _fake_transport(
        [PAGE_A], {"TARGET_A": {"href": YT_URL, "current": 1519.724521}})
    resolved = cdp.resolve_chromium_media(
        window_title=TITLE, position_us=1_519_724_521, config_root=tmp_path,
        connect=connect, get_targets=get_targets, evaluate=evaluate,
    )
    assert resolved["media_source"] == YT_URL
    assert resolved["media_id"] == YT_ID


def test_resolve_chromium_media_missing_port_file_returns_none(tmp_path):
    connect, get_targets, evaluate = _fake_transport([], {})
    assert cdp.resolve_chromium_media(
        window_title=TITLE, config_root=tmp_path, connect=connect,
        get_targets=get_targets, evaluate=evaluate) is None


def test_resolve_chromium_media_tries_next_profile(tmp_path):
    (tmp_path / "google-chrome").mkdir(exist_ok=True)  # no port file here
    (tmp_path / "chromium").mkdir(exist_ok=True)
    (tmp_path / "chromium" / "DevToolsActivePort").write_text(
        "9222\n/devtools/browser/uuid\n")
    connect, get_targets, evaluate = _fake_transport(
        [PAGE_A], {"TARGET_A": {"href": YT_URL, "current": 900.0}})
    resolved = cdp.resolve_chromium_media(
        window_title=TITLE, position_us=900_000_000, config_root=tmp_path,
        connect=connect, get_targets=get_targets, evaluate=evaluate,
    )
    assert resolved["media_id"] == YT_ID


# ---- daemon wiring ----

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


def test_watch_poll_enriches_chromium_session_with_cdp(tmp_path):
    """A poll tick resolves the exact URL + video id for a live Chromium
    session and the closed session keeps them."""
    resolver = lambda title, pos: {"media_source": YT_URL, "media_id": YT_ID}
    tools = _FakeWatchTools(players=["chromium.instance1220"],
                            position=910_000_000, cdp_resolve=resolver)
    daemon = _daemon(tmp_path, tools)
    daemon._on_track(CHROME_LINE)

    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["media_source"] is None  # MPRIS carries no URL for Chromium

    daemon._watch_poll_once()

    item = daemon.db.get_watch_session(items[0]["id"])
    assert item["media_source"] == YT_URL
    assert item["media_id"] == YT_ID
    assert item["live"] == 1

    snap = {s.player: s for s in daemon.tracker.snapshot()}
    assert snap["chromium"].media_source == YT_URL
    assert snap["chromium"].media_id == YT_ID

    daemon._on_track(STOPPED_CHROME)
    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["live"] == 1  # a stopped(0) is a tab hide, not an end
    assert items[0]["media_source"] == YT_URL
    assert items[0]["media_id"] == YT_ID


def test_watch_poll_cdp_unreachable_keeps_title_only(tmp_path):
    """A resolver that fails (CDP down, no port file) leaves the session
    title-only and never crashes the poll loop."""
    tools = _FakeWatchTools(players=["chromium.instance1220"],
                            position=910_000_000, cdp_resolve=lambda t, p: None)
    daemon = _daemon(tmp_path, tools)
    daemon._on_track(CHROME_LINE)

    daemon._watch_poll_once()

    total, items = daemon.db.list_watch_sessions()
    assert items[0]["live"] == 1
    assert items[0]["media_source"] is None
    assert items[0]["media_id"] is None

    daemon._on_track(STOPPED_CHROME)
    item = daemon.db.get_watch_session(items[0]["id"])
    assert item["live"] == 1  # tab hide keeps the session (CDP data intact)
    assert item["media_source"] is None
    assert item["media_id"] is None


def test_watch_poll_only_resolves_chromium_without_media(tmp_path):
    """CDP is only asked about open Chromium sessions still missing media:
    VLC sessions and already-resolved Chromium sessions are left alone."""
    calls: list[tuple] = []

    def resolver(title, pos):
        calls.append((title, pos))
        return {"media_source": YT_URL, "media_id": YT_ID}

    tools = _FakeWatchTools(players=["chromium.instance1220"],
                            position=900_000_000, cdp_resolve=resolver)
    daemon = _daemon(tmp_path, tools)
    vlc = "Playing|Hans Zimmer|Inception (2010)||vlc|900000000|7200000000|file:///mnt/movies/Inception.mkv"
    daemon._on_track(vlc)
    already = f"Playing||{TITLE}||chromium|900000000|7200000000|{YT_URL}"
    daemon._on_track(already)

    daemon._watch_poll_once()
    assert calls == []  # vlc has a URL; chromium already resolved

    daemon._on_track(CHROME_LINE)  # a fresh chromium session, no URL
    daemon._watch_poll_once()
    assert len(calls) == 1
    assert calls[0][0] == TITLE
    assert calls[0][1] == 900_000_000
