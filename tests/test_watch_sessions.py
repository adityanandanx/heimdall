"""Watch-session storage (v2 #35): DB round-trips, FTS, and the daemon wiring
that turns MPRIS follow lines + position polls into persisted sessions."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlite3

from heimdall.capture.daemon import CaptureDaemon
from heimdall.capture.sessions import SessionTracker
from heimdall.config import Config
from heimdall.db import Database, init_db

VLC_LINE = "Playing|Hans Zimmer|Inception (2010)||vlc|900000000|7200000000|file:///mnt/movies/Inception.mkv"
PAUSED_VLC = "Paused|Hans Zimmer|Inception (2010)||vlc|1200000000|7200000000|file:///mnt/movies/Inception.mkv"
STOPPED_VLC = "Stopped||||vlc|0|0|"


def _closed_session(player="vlc", title="Inception (2010)",
                    source="file:///mnt/movies/Inception.mkv"):
    t = SessionTracker()
    t.play(player, title=title, source=source, position_us=600_000_000,
           length_us=7_200_000_000, wall_ms=1_000)
    return t.stop(player, position_us=900_000_000, wall_ms=130_000)


# ---- storage ----

def test_watch_sessions_created_on_fresh_db(tmp_path):
    path = tmp_path / "db.sqlite"
    init_db(path)
    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'watch_sessions%'")}
    conn.close()
    assert "watch_sessions" in tables
    assert "watch_sessions_fts" in tables


def test_insert_list_get_roundtrip(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    init_db(db.path)
    id_a = db.insert_watch_session(_closed_session(player="vlc"))
    id_b = db.insert_watch_session(_closed_session(
        player="chromium.instance1", title="Rick Astley - Never Gonna Give You Up",
        source=None))

    total, items = db.list_watch_sessions()
    assert total == 2
    # newest first
    assert [it["player"] for it in items] == ["chromium.instance1", "vlc"]
    item = items[0]
    for key in ("id", "player", "media_title", "media_source", "media_id",
                "ts_start", "ts_end", "pos_start", "pos_end", "length", "ranges"):
        assert key in item
    assert item["ranges"] == [[600_000_000, 900_000_000]]
    assert item["media_source"] is None

    detail = db.get_watch_session(id_a)
    assert detail["player"] == "vlc"
    assert detail["media_source"] == "file:///mnt/movies/Inception.mkv"
    assert detail["ranges"] == [[600_000_000, 900_000_000]]
    assert db.get_watch_session(9999) is None


def test_list_watch_sessions_filters(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    init_db(db.path)
    for i in range(4):
        db.insert_watch_session(_closed_session(player="vlc" if i % 2 == 0 else "sidra"))

    total, items = db.list_watch_sessions(player="vlc")
    assert total == 2
    assert all(it["player"] == "vlc" for it in items)

    total, items = db.list_watch_sessions(start=1_000, end=50_000)
    assert total == 4
    total, items = db.list_watch_sessions(start=100_000)
    assert total == 0

    total, items = db.list_watch_sessions(limit=2, offset=2)
    assert total == 4
    assert len(items) == 2


def test_search_watch_sessions_fts(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    init_db(db.path)
    db.insert_watch_session(_closed_session())
    db.insert_watch_session(_closed_session(
        player="chromium.instance1", title="Rick Astley - Never Gonna Give You Up",
        source="https://youtube.com/watch?v=dQw4w9WgXcQ"))

    total, items = db.search_watch_sessions("Inception")
    assert total == 1
    assert items[0]["media_title"] == "Inception (2010)"
    assert "**Inception**" in items[0]["snippet"]

    total, items = db.search_watch_sessions("youtube")
    assert total == 1
    assert items[0]["player"] == "chromium.instance1"

    with pytest.raises(sqlite3.OperationalError):
        db.search_watch_sessions("inception AND (")


# ---- daemon wiring ----

class _FakeWatchTools:
    """CaptureTools stand-in: follow lines come from _on_track directly; the
    poll seam (list_players / playerctl_position) is controllable."""

    def __init__(self, players=None, position=None):
        self.players = list(players or [])
        self._position = position

    def list_players(self) -> list[str]:
        return list(self.players)

    def playerctl_position(self, player: str):
        return self._position


def _daemon(tmp_path: Path, tools) -> CaptureDaemon:
    daemon = CaptureDaemon(Config(data_dir=tmp_path), tools=tools)
    init_db(path=daemon.db_path)
    return daemon


def test_follow_lines_drive_session_persistence(tmp_path):
    """play -> pause -> resume -> stop: one VLC session with the exact file
    path, title and a continuous video-time range (wall pauses excluded)."""
    daemon = _daemon(tmp_path, _FakeWatchTools())
    daemon._on_track(VLC_LINE)
    daemon._on_track(PAUSED_VLC)
    daemon._on_track(PAUSED_VLC.replace("Paused", "Playing"))
    daemon._on_track(STOPPED_VLC)

    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    session = items[0]
    assert session["player"] == "vlc"
    assert session["media_title"] == "Inception (2010)"
    assert session["media_source"] == "file:///mnt/movies/Inception.mkv"
    assert session["pos_start"] == 900_000_000
    assert session["ranges"] == [[900_000_000, 1_200_000_000]]
    assert session["ts_start"] <= session["ts_end"]


def test_mid_play_track_switch_finalizes_old_and_opens_new_live_row(tmp_path):
    """A different title while playing finalizes the old live row and opens a
    new live one (MPRIS emits no stopped between tracks)."""
    daemon = _daemon(tmp_path, _FakeWatchTools())
    daemon._on_track(VLC_LINE)
    daemon._on_track("Playing|Hans Zimmer|Time||vlc|1500000000|7200000000|file:///mnt/movies/Inception.mkv")

    total, items = daemon.db.list_watch_sessions()
    assert total == 2  # the old "Inception (2010)" row finalized, "Time" live
    by_live = {it["live"]: it for it in items}
    old, new = by_live[0], by_live[1]
    assert old["media_title"] == "Inception (2010)"
    assert old["pos_end"] == 0  # position unknown at a mid-play switch
    assert old["ranges"] == []  # degenerate segment is dropped (#65)
    assert new["media_title"] == "Time"
    assert new["live"] == 1
    assert new["ts_end"] == 0
    assert len(daemon.tracker.open_sessions()) == 1  # "Time" still open


def test_watch_poll_persists_on_player_exit(tmp_path):
    """A player that vanishes from `playerctl -l` closes + finalizes its session."""
    tools = _FakeWatchTools(players=["vlc"])
    daemon = _daemon(tmp_path, tools)
    daemon._on_track(VLC_LINE)
    assert daemon.db.list_watch_sessions()[0] == 1
    tools.players = []
    daemon._watch_poll_once()

    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["live"] == 0
    assert items[0]["pos_end"] == 0  # unknown position at exit
    assert items[0]["ranges"] == []  # degenerate segment is dropped (#65)
    assert daemon._live_rows == {}


def test_watch_poll_matches_instanced_player_name(tmp_path):
    """`playerctl -l` returns instance names (chromium.instance1220) while the
    tracker keys by the base `{{playerName}}` (chromium); the poll must not
    treat that as a player exit."""
    tools = _FakeWatchTools(players=["chromium.instance1220"], position=910_000_000)
    daemon = _daemon(tmp_path, tools)
    daemon._on_track("Playing||My Video||chromium|900000000|7200000000|file:///v/my.mp4")

    daemon._watch_poll_once()
    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["live"] == 1  # still open, not exited
    assert items[0]["pos_end"] == 910_000_000  # position still recorded
    assert daemon._live_rows != {}


def test_watch_poll_updates_live_row_for_later_close(tmp_path):
    """The 30s poll updates the live row's last known position, so a later
    close keeps the full watched range even when MPRIS reports position 0."""
    tools = _FakeWatchTools(players=["vlc"], position=910_000_000)
    daemon = _daemon(tmp_path, tools)
    daemon._on_track(VLC_LINE)
    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["live"] == 1  # open session persisted as a live row
    row_id = items[0]["id"]

    daemon._watch_poll_once()  # still playing -> no close, position recorded
    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["id"] == row_id  # updated in place, not re-inserted
    assert items[0]["live"] == 1
    assert items[0]["pos_end"] == 910_000_000
    assert items[0]["ranges"] == []  # only closed ranges persist while live

    daemon._on_track(STOPPED_VLC)
    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["live"] == 0
    assert items[0]["ranges"] == [[900_000_000, 910_000_000]]


def test_open_session_is_persisted_as_live_row(tmp_path):
    """Playing opens a watch_sessions row immediately (live=1, ts_end=0)."""
    daemon = _daemon(tmp_path, _FakeWatchTools())
    daemon._on_track(VLC_LINE)
    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    item = items[0]
    assert item["live"] == 1
    assert item["ts_end"] == 0
    assert item["pos_start"] == 900_000_000
    assert item["pos_end"] == 900_000_000
    assert item["player"] == "vlc"
    assert item["media_title"] == "Inception (2010)"
    assert item["media_source"] == "file:///mnt/movies/Inception.mkv"
    assert item["ranges"] == []  # only closed ranges are persisted while live
    assert daemon._live_rows == {"vlc": item["id"]}


def test_stop_finalizes_live_row(tmp_path):
    """A stopped line (position 0) finalizes the live row in place."""
    daemon = _daemon(tmp_path, _FakeWatchTools())
    daemon._on_track(VLC_LINE)
    daemon._on_track(STOPPED_VLC)
    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    item = items[0]
    assert item["live"] == 0
    assert item["pos_end"] == 0  # MPRIS reports position 0 on stop
    assert item["ranges"] == []  # degenerate segment is dropped (#65)
    assert item["ts_end"] >= item["ts_start"]
    assert daemon._live_rows == {}


def test_pause_over_threshold_closes_via_poll(tmp_path):
    """A pause > pause_ends_session_s closes the session from the poll loop."""
    tools = _FakeWatchTools(players=["vlc"], position=1_200_000_000)
    daemon = _daemon(tmp_path, tools)
    daemon.tracker.pause_ends_session_s = -1.0  # any pause is over the threshold
    daemon._on_track(VLC_LINE)
    daemon._on_track(PAUSED_VLC)
    daemon._watch_poll_once()  # paused, threshold crossed -> closes

    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["pos_end"] == 1_200_000_000
    assert items[0]["ranges"] == [[900_000_000, 1_200_000_000]]


# ---- chromium stopped(0) is a tab-hide, not a session end ----

CHROMIUM_LINE = "Playing||Little Coder||chromium|754000000|213000000|"
CHROMIUM_STOPPED = "Stopped||Little Coder||chromium|0|0|"

def test_chromium_stopped_hide_keeps_live_row(tmp_path):
    """A stopped(0) from Chromium is a tab hiding: the live row stays open and
    a resume continues the same session instead of finalizing a 2-row pair."""
    tools = _FakeWatchTools(players=["chromium.instance1220"], position=755_000_000)
    daemon = _daemon(tmp_path, tools)
    daemon._on_track(CHROMIUM_LINE)
    daemon._on_track(CHROMIUM_STOPPED)  # tab hidden
    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["live"] == 1
    assert len(daemon.tracker.open_sessions()) == 1

    daemon._on_track(CHROMIUM_LINE)  # tab visible again
    total, items = daemon.db.list_watch_sessions()
    assert total == 1  # same row: hide/show is one session
    assert items[0]["live"] == 1
    assert items[0]["pos_start"] == 754_000_000


def test_chromium_absent_poll_does_not_exit(tmp_path):
    """Chromium deregisters its MPRIS instance while hidden, so missing from
    `playerctl -l` must not end the session."""
    tools = _FakeWatchTools(players=[], position=None)
    daemon = _daemon(tmp_path, tools)
    daemon._on_track(CHROMIUM_LINE)
    daemon._watch_poll_once()
    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["live"] == 1  # absence alone never closes chromium
    assert len(daemon.tracker.open_sessions()) == 1


def test_chromium_stale_past_threshold_closes_dead_tab(tmp_path):
    """A tab that is truly gone (no lines, absent player, > threshold) closes."""
    tools = _FakeWatchTools(players=[], position=None)
    daemon = _daemon(tmp_path, tools)
    daemon.tracker.pause_ends_session_s = -1.0  # any silence is over threshold
    daemon._on_track(CHROMIUM_LINE)
    daemon._on_track(CHROMIUM_STOPPED)
    daemon._watch_poll_once()
    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["live"] == 0
    assert items[0]["pos_end"] == 0
    assert daemon._live_rows == {}


def test_vlc_stopped_zero_still_closes_instantly(tmp_path):
    """Non-chromium players keep the old stop semantics: stopped(0) exits."""
    tools = _FakeWatchTools(players=["vlc"], position=900_000_000)
    daemon = _daemon(tmp_path, tools)
    daemon._on_track(VLC_LINE)
    daemon._on_track(STOPPED_VLC)
    total, items = daemon.db.list_watch_sessions()
    assert total == 1
    assert items[0]["live"] == 0
    assert items[0]["pos_end"] == 0
