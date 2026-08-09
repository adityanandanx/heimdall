"""MPRIS -> watch-session state machine (pure, secondary seam, spec #20 / #35).

The tracker is driven by abstract events (play/pause/poll/seek/stop/exit) with
explicit wall clocks, so play/pause/seek/quit/player-exit sequences are fully
deterministic. Positions are video-time microseconds; ts_* are wall ms.
"""

from __future__ import annotations

from heimdall.capture.sessions import (
    SessionTracker,
    fmt_video_time,
    is_seek,
    normalize_player,
    parse_mpris_line,
)


def _play(t, *, player="vlc", title="Inception (2010)",
          source="file:///mnt/movies/Inception.mkv", position_us=0,
          length_us=7_200_000_000, wall_ms=0):
    return t.play(player=player, title=title, source=source, position_us=position_us,
                  length_us=length_us, wall_ms=wall_ms)


# ---- play -> stop ----

def test_play_then_stop_creates_one_session():
    t = SessionTracker()
    _play(t, position_us=600_000_000, wall_ms=1_000)
    assert len(t.open_sessions()) == 1
    closed = t.stop(player="vlc", position_us=900_000_000, wall_ms=130_000)
    assert closed is not None
    assert closed.player == "vlc"
    assert closed.media_title == "Inception (2010)"
    assert closed.media_source == "file:///mnt/movies/Inception.mkv"
    assert closed.media_id is None
    assert closed.ts_start == 1_000
    assert closed.ts_end - closed.ts_start == 129_000  # wall span while playing
    assert closed.pos_start == 600_000_000
    assert closed.pos_end == 900_000_000
    assert closed.length == 7_200_000_000
    assert closed.ranges == [[600_000_000, 900_000_000]]
    assert t.open_sessions() == []


def test_stop_without_session_is_noop():
    t = SessionTracker()
    assert t.stop(player="vlc", position_us=0, wall_ms=0) is None


# ---- pause < 60s does not close; wall excludes the pause ----

def test_short_pause_resume_is_one_session_and_wall_excludes_pause():
    t = SessionTracker()
    _play(t, wall_ms=1_000)
    t.pause(player="vlc", position_us=30_000_000, wall_ms=31_000)   # played 30s
    assert len(t.open_sessions()) == 1                              # still open
    _play(t, position_us=30_000_000, wall_ms=51_000)                # resume after 20s pause
    closed = t.stop(player="vlc", position_us=60_000_000, wall_ms=81_000)  # played 30s more
    assert closed is not None
    assert closed.ts_start == 1_000
    # wall time accrued only while playing: 30s + 30s, the 20s pause excluded
    assert closed.ts_end - closed.ts_start == 60_000
    assert closed.ranges == [[0, 60_000_000]]


# ---- pause > 60s closes (via poll); resume opens a new session ----

def test_pause_over_threshold_closes_then_resume_opens_new():
    t = SessionTracker(pause_ends_session_s=60.0)
    _play(t, wall_ms=0)
    t.pause(player="vlc", position_us=30_000_000, wall_ms=30_000)
    # first poll after 30s paused: still open
    assert t.poll(player="vlc", position_us=30_000_000, wall_ms=60_000) is None
    assert len(t.open_sessions()) == 1
    # second poll crosses 60s -> closed
    closed = t.poll(player="vlc", position_us=30_000_000, wall_ms=100_000)
    assert closed is not None
    assert closed.ts_start == 0
    assert closed.ts_end - closed.ts_start == 30_000  # only the played 30s
    assert closed.pos_end == 30_000_000
    assert t.open_sessions() == []
    # resume after the close starts a fresh session
    _play(t, position_us=30_000_000, wall_ms=110_000)
    assert len(t.open_sessions()) == 1
    closed2 = t.stop(player="vlc", position_us=40_000_000, wall_ms=120_000)
    assert closed2.ts_start == 110_000
    assert closed2.pos_start == 30_000_000
    assert closed2.pos_end == 40_000_000


# ---- seek splits ranges; skipped segment excluded ----

def test_seek_splits_ranges_and_excludes_skipped_segment():
    t = SessionTracker()
    _play(t, wall_ms=0)
    t.poll(player="vlc", position_us=120_000_000, wall_ms=120_000)     # watched to 2:00
    t.seek(player="vlc", position_us=600_000_000, wall_ms=130_000)     # jump to 10:00
    closed = t.stop(player="vlc", position_us=660_000_000, wall_ms=190_000)  # watch to 11:00
    assert closed.ranges == [[0, 120_000_000], [600_000_000, 660_000_000]]
    # the skipped segment 2:00..10:00 does not appear in the watched ranges


def test_seek_backwards_still_splits():
    t = SessionTracker()
    _play(t, wall_ms=0)
    t.poll(player="vlc", position_us=300_000_000, wall_ms=300_000)
    t.seek(player="vlc", position_us=30_000_000, wall_ms=310_000)  # rewind to 0:30
    closed = t.stop(player="vlc", position_us=90_000_000, wall_ms=360_000)
    assert closed.ranges == [[0, 300_000_000], [30_000_000, 90_000_000]]


# ---- snapshot: read-only view of open sessions for live rows ----

def test_snapshot_reports_open_playing_session():
    t = SessionTracker()
    _play(t, position_us=600_000_000, wall_ms=1_000)
    t.poll(player="vlc", position_us=630_000_000, wall_ms=31_000)
    snap = t.snapshot()
    assert len(snap) == 1
    s = snap[0]
    assert s.player == "vlc"
    assert s.media_title == "Inception (2010)"
    assert s.media_source == "file:///mnt/movies/Inception.mkv"
    assert s.media_id is None
    assert s.ts_start == 1_000
    assert s.pos_start == 600_000_000
    assert s.length == 7_200_000_000
    assert s.last_pos_us == 630_000_000
    assert s.ranges == []
    assert s.paused is False
    assert s.paused_at_wall_ms is None
    # the session is untouched by snapshot()
    assert len(t.open_sessions()) == 1


def test_snapshot_reports_paused_session():
    t = SessionTracker()
    _play(t, position_us=600_000_000, wall_ms=1_000)
    t.pause(player="vlc", position_us=630_000_000, wall_ms=31_000)
    s = t.snapshot()[0]
    assert s.paused is True
    assert s.paused_at_wall_ms == 31_000
    assert s.last_pos_us == 630_000_000


def test_snapshot_includes_wall_accrual_and_streak_fields():
    t = SessionTracker()
    _play(t, position_us=600_000_000, wall_ms=1_000)
    t.poll(player="vlc", position_us=630_000_000, wall_ms=31_000)
    t.pause(player="vlc", position_us=630_000_000, wall_ms=31_000)  # closes the streak
    s = t.snapshot()[0]
    assert s.acc_wall_ms == 30_000
    assert s.streak_start_wall_ms is None  # paused: no streak running
    assert s.paused_at_wall_ms == 31_000


def test_snapshot_empty_when_no_open_sessions():
    t = SessionTracker()
    _play(t, wall_ms=1_000)
    t.stop(player="vlc", position_us=900_000_000, wall_ms=130_000)
    assert t.snapshot() == []


def test_snapshot_does_not_advance_or_close_anything():
    t = SessionTracker(pause_ends_session_s=0.001)
    _play(t, position_us=600_000_000, wall_ms=1_000)
    t.pause(player="vlc", position_us=630_000_000, wall_ms=31_000)
    t.snapshot()  # reading must not close a past-threshold paused session
    assert len(t.open_sessions()) == 1
    assert t.snapshot()[0].paused is True


# ---- player-exit ----

def test_player_exit_closes_session():
    t = SessionTracker()
    _play(t, player="chromium.instance1", title="Rick Astley - Never Gonna Give You Up",
          source=None, length_us=213_000_000, wall_ms=0)
    closed = t.exit(player="chromium.instance1", wall_ms=90_000)
    assert closed is not None
    assert closed.ts_end - closed.ts_start == 90_000
    assert closed.pos_end == 0  # no position known at exit
    assert t.open_sessions() == []


def test_exit_without_session_is_noop():
    t = SessionTracker()
    assert t.exit(player="vlc", wall_ms=0) is None


# ---- chromium sessions are title-only until CDP (#36) ----

def test_chromium_session_records_title_and_position_only():
    t = SessionTracker()
    t.play(player="chromium.instance1", title="Rick Astley - Never Gonna Give You Up",
           source=None, media_id=None, position_us=60_000_000,
           length_us=213_000_000, wall_ms=0)
    closed = t.stop(player="chromium.instance1", position_us=90_000_000, wall_ms=30_000)
    assert closed.player == "chromium.instance1"
    assert closed.media_source is None
    assert closed.media_id is None
    assert closed.pos_start == 60_000_000
    assert closed.pos_end == 90_000_000


# ---- parsing the playerctl follow line ----

def test_parse_mpris_line_vlc():
    line = "Playing|Hans Zimmer|Inception (2010)|||vlc|900000000|7200000000|file:///mnt/movies/Inception.mkv"
    assert parse_mpris_line(line) == {
        "player": "vlc",
        "status": "playing",
        "title": "Inception (2010)",
        "position_us": 900_000_000,
        "length_us": 7_200_000_000,
        "source": "file:///mnt/movies/Inception.mkv",
    }


def test_parse_mpris_line_chromium_title_only():
    line = "Playing|Rick Astley|Never Gonna Give You Up||chromium.instance1|90000000|213000000|"
    parsed = parse_mpris_line(line)
    assert parsed["player"] == "chromium.instance1"
    assert parsed["status"] == "playing"
    assert parsed["position_us"] == 90_000_000
    assert parsed["source"] is None


def test_parse_mpris_line_statuses_and_garbage():
    assert parse_mpris_line("Stopped|||vlc||0|0|")["status"] == "stopped"
    assert parse_mpris_line("Paused|||vlc||0|0|")["status"] == "paused"
    assert parse_mpris_line("") is None
    assert parse_mpris_line("garbage") is None
    assert parse_mpris_line("Playing|||vlc") is None  # too few fields


def test_parse_mpris_line_handles_empty_numbers():
    line = "Playing||Some Video||chromium.instance2|||0|"
    parsed = parse_mpris_line(line)
    assert parsed["position_us"] == 0
    assert parsed["length_us"] == 0


# ---- seek detection helper ----

def test_is_seek():
    assert is_seek(0, 90_000_000, elapsed_s=30) is True        # 90s jumped in 30s
    assert is_seek(120_000_000, 30_000_000, elapsed_s=30) is True  # rewind
    assert is_seek(0, 30_000_000, elapsed_s=30) is False       # normal 1x playback
    assert is_seek(0, 60_000_000, elapsed_s=30) is False       # 2x playback is linear
    assert is_seek(0, 45_000_000, elapsed_s=30) is False       # 1.5x playback is linear
    assert is_seek(0, 30_000_000, elapsed_s=30, tolerance_s=45) is False  # loose tolerance


def test_is_seek_rate_aware():
    # At the 30s poll cadence, 2x lands well inside the 2x+slack headroom;
    # only >2x bursts or rewinds split the range (#66).
    assert is_seek(60_000_000, 120_000_000, elapsed_s=30) is False  # 2x forever: one range
    assert is_seek(60_000_000, 150_000_000, elapsed_s=30) is True   # 3x burst: real skip
    assert is_seek(0, 60_000_000, elapsed_s=60) is False            # 2x over 60s: still fine
    assert is_seek(0, 180_000_000, elapsed_s=60) is True            # 3x over 60s: seek
    assert is_seek(120_000_000, 30_000_000, elapsed_s=30) is True   # rewind always splits


# ---- player normalization + video time formatting ----

def test_normalize_player():
    assert normalize_player("vlc") == "vlc"
    assert normalize_player("chromium.instance1") == "chromium"
    assert normalize_player("chromium") == "chromium"
    assert normalize_player("sidra") == "sidra"


def test_fmt_video_time():
    assert fmt_video_time(0) == "0:00"
    assert fmt_video_time(60_000_000) == "1:00"
    assert fmt_video_time(1_200_000_000) == "20:00"
    assert fmt_video_time(7_200_000_000) == "2:00:00"
    assert fmt_video_time(-5) == "0:00"


def test_poll_rewind_never_records_inverted_range():
    """A position behind the range start at a poll is a rewind mid-streak (#65):
    the closed segment is dropped instead of persisted backwards."""
    t = SessionTracker()
    _play(t, wall_ms=0)
    t.poll(player="vlc", position_us=120_000_000, wall_ms=120_000)
    t.poll(player="vlc", position_us=60_000_000, wall_ms=121_000)  # rewound 1:00
    closed = t.stop(player="vlc", position_us=90_000_000, wall_ms=180_000)
    # the pre-rewind chunk [0, 120s] survives; the rewind span is not inverted
    assert closed.ranges == [[0, 120_000_000], [60_000_000, 90_000_000]]


def test_ranges_clamped_to_known_length():
    """A65: a restart-clock overshoot must never count past the video end."""
    t = SessionTracker()
    _play(t, wall_ms=0, length_us=100_000_000)
    t.poll(player="vlc", position_us=95_000_000, wall_ms=95_000)
    t.seek(player="vlc", position_us=200_000_000, wall_ms=180_000)
    closed = t.stop(player="vlc", position_us=30_000_000, wall_ms=190_000)
    assert closed.length == 100_000_000
    # [0, 95s] kept; the post-length seek span is clamped away entirely
    assert closed.ranges == [[0, 95_000_000]]


# ---- Chromium throttled bursts: silence then a stale+caught-up pair (#repro) ----

def test_chromium_throttled_burst_does_not_split_session():
    """Chromium in a background tab updates in bursts: after a ~30s silence a
    line carries a stale position, the next (1s later) the caught-up position,
    and the pair differs on title/source. That is one continuous watch."""
    t = SessionTracker()
    _play(t, player="chromium.instance1", title="Quickshell bar on Hyprland",
          source=None, position_us=0, wall_ms=0)
    t.poll(player="chromium.instance1", position_us=0, wall_ms=30_000)
    # burst: stale line (title loses the suffix, source still absent)
    t.play(player="chromium.instance1", title="Quickshell bar on Hyprland",
           source=None, position_us=0, wall_ms=60_001)
    # burst: fresh line, same media, title/source differ, position caught up
    t.play(player="chromium.instance1", title="Quickshell bar on Hyprland - Chromium",
           source="https://www.youtube.com/watch?v=x", position_us=30_000_000, wall_ms=61_001)
    assert t.open_sessions() == ["chromium.instance1"]
    closed = t.stop(player="chromium.instance1", position_us=60_000_000, wall_ms=91_000)
    assert closed is not None
    assert closed.media_title == "Quickshell bar on Hyprland - Chromium"
    assert closed.ts_end - closed.ts_start == 58_999  # silent video counted (~60s watched)
    assert closed.ranges == [[0, 60_000_000]]


def test_chromium_burst_with_real_track_switch_still_closes():
    # a genuine switch: new title, position reset near 0 (backwards) closes
    t = SessionTracker()
    _play(t, player="chromium.instance1", title="First video", position_us=90_000_000, wall_ms=0)
    t.poll(player="chromium.instance1", position_us=95_000_000, wall_ms=5_000)
    closed = t.play(player="chromium.instance1", title="Second video",
                    source=None, position_us=0, wall_ms=6_000)
    assert closed is not None
    assert closed.pos_start == 90_000_000
    assert t.open_sessions() == ["chromium.instance1"]


def test_chromium_flat_position_mismatch_still_closes():
    # a mismatch without position progress (playlist track change) closes
    t = SessionTracker()
    _play(t, player="chromium.instance1", title="Track A", position_us=120_000_000, wall_ms=0)
    t.poll(player="chromium.instance1", position_us=121_000_000, wall_ms=1_000)
    closed = t.play(player="chromium.instance1", title="Track B",
                    source=None, position_us=121_500_000, wall_ms=2_000)  # +0.5s in 1s wall
    assert closed is not None
    assert t.open_sessions() == ["chromium.instance1"]


def test_pause_after_silent_stretch_accrues_watched_video():
    # a pause line after throttled silence: position advanced far beyond the
    # wall span between the last line and the pause -> banked into acc_wall
    t = SessionTracker()
    _play(t, player="chromium.instance1", title="Video", position_us=0, wall_ms=0)
    # 29s of video happens while only 1s of wall passes between lines
    _play(t, player="chromium.instance1", title="Video", source=None,
          position_us=29_000_000, wall_ms=1_000)
    t.pause(player="chromium.instance1", position_us=60_000_000, wall_ms=2_000)
    s = t.snapshot()[0]
    assert s.acc_wall_ms == 60_000 - 1_000  # 1s line span + 29s caught up + pause's 30s


# ---- chromium tab-hide: stopped(0) suspends, absence stales ----

def test_suspend_keeps_session_and_last_position():
    t = SessionTracker()
    _play(t, player="chromium", title="Video", source=None, position_us=50_000_000, wall_ms=0)
    t.suspend(player="chromium", wall_ms=40_000)
    s = t.snapshot()[0]
    assert s.paused is True
    assert s.last_pos_us == 50_000_000  # closed at the real position, not 0
    assert s.acc_wall_ms == 40_000


def test_suspend_then_playing_resumes_same_session():
    t = SessionTracker()
    _play(t, player="chromium", title="Video", source=None, position_us=50_000_000, wall_ms=0)
    t.suspend(player="chromium", wall_ms=40_000)
    _play(t, player="chromium", title="Video", source=None, position_us=50_000_000, wall_ms=46_000)
    closed = t.stop(player="chromium", position_us=80_000_000, wall_ms=76_000)
    assert closed is not None
    assert closed.pos_start == 50_000_000
    assert closed.ts_start == 0  # one continuous session across the hide
    assert t.open_sessions() == []


def test_stale_closes_paused_session_past_threshold():
    t = SessionTracker()
    _play(t, player="chromium", title="Video", source=None, position_us=50_000_000, wall_ms=0)
    t.suspend(player="chromium", wall_ms=1_000)
    assert t.stale(player="chromium", wall_ms=30_000) is None   # inside threshold
    closed = t.stale(player="chromium", wall_ms=90_000)         # > 60s
    assert closed is not None
    assert closed.pos_end == 0  # no position known on a dead tab
    assert closed.ranges == []


def test_stale_closes_frozen_playing_session():
    t = SessionTracker()
    _play(t, player="chromium", title="Video", source=None, position_us=50_000_000, wall_ms=0)
    assert t.stale(player="chromium", wall_ms=10_000) is None   # live, fresh
    closed = t.stale(player="chromium", wall_ms=90_000)         # no lines for 90s
    assert closed is not None
    assert t.open_sessions() == []
