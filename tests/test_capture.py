"""Secondary seam: capture event parsing, trigger classification, debounce,
dedupe + span-timing computation with crafted sequences."""

from __future__ import annotations

from heimdall.capture.events import (
    activewindow_signature,
    classify_trigger,
    debounce_burst,
    is_duplicate,
    is_track_change,
    parse_socket2_line,
    should_capture,
    workspace_id,
)
from heimdall.capture.spans import compute_spans, rules_minutes, spans_to_table, track_playing_ms


# ---- socket2 parsing / classification ----

def test_parse_socket2_line():
    assert parse_socket2_line("activewindow>>kitty,My Window") == {
        "type": "activewindow", "payload": "kitty,My Window",
    }
    assert parse_socket2_line("") is None
    assert parse_socket2_line("garbage") is None


def test_classify_trigger():
    assert classify_trigger("activewindow") == "activewindow"
    assert classify_trigger("activewindowv2") == "activewindow"
    assert classify_trigger("openwindow") == "openwindow"
    assert classify_trigger("workspacev2") == "workspace"
    assert classify_trigger("fullscreen") == "fullscreen"
    assert classify_trigger("windowtitlev2") == "windowtitle"
    assert classify_trigger("screencast") is None
    assert classify_trigger("closewindow") is None
    assert classify_trigger("focusedmon") is None


def test_debounce_collapses_burst():
    burst = [(0.0, "activewindow"), (0.1, "workspace"), (0.2, "activewindow"),
             (5.0, "fullscreen")]
    fires = debounce_burst(burst, debounce_s=1.5)
    assert len(fires) == 2
    first = fires[0]
    assert first[0] == 0.0  # burst start ts
    assert first[1] == "activewindow"  # last event's trigger in burst
    assert abs(first[2] - 1.7) < 1e-9  # last event ts + debounce
    assert fires[1][1] == "fullscreen"


def test_debounce_single_event():
    fires = debounce_burst([(3.0, "workspace")], debounce_s=1.5)
    assert fires == [(3.0, "workspace", 4.5)]


def test_should_capture_min_interval():
    assert should_capture(now=10.0, last_fire=0.0, min_interval_s=10) is True
    assert should_capture(now=10.0, last_fire=0.1, min_interval_s=10) is False
    assert should_capture(now=10.0, last_fire=0.1, min_interval_s=10) is False


def test_duplicate_and_signature():
    meta = {"class": "firefox", "title": "yt", "workspace": {"id": 1, "name": "1"}}
    sig = activewindow_signature(meta)
    assert sig == ("firefox", "yt", "1:1")
    assert is_duplicate(sig, sig) is True
    assert is_duplicate(sig, ("firefox", "yt2", "1:1")) is False
    assert is_duplicate(None, sig) is False
    assert workspace_id(meta) == 1
    assert workspace_id({"workspace": None}) is None
    assert workspace_id({}) is None


def test_is_track_change():
    # first sighting always counts as a change
    assert is_track_change(None, "sidra", "Tycho", "Awake") is True
    last = ("sidra", "Tycho", "Awake")
    assert is_track_change(last, "sidra", "Tycho", "Awake") is False
    # new song while still playing must be a capture trigger
    assert is_track_change(last, "sidra", "Tycho", "Epoch") is True
    assert is_track_change(last, "spotify", "Tycho", "Awake") is True
    # artist/title missing both ways still compares on what is present
    assert is_track_change(("sidra", "Tycho", ""), "sidra", "Tycho", "") is False


def test_mpris_on_track_enqueues_only_on_play_or_change(tmp_path):
    """Daemon wiring: playerctl --follow only emits on metadata/status changes,
    so play, resume and track-switch fire; a same-track pause does not (#5)."""
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config
    from heimdall.db import init_db

    daemon = CaptureDaemon(Config(data_dir=tmp_path))
    init_db(path=daemon.db_path)
    daemon._on_track("playing|Tycho|Awake|Epoch|sidra")  # play -> fire
    daemon._on_track("paused|Tycho|Awake|Epoch|sidra")   # same track, pause -> no
    assert daemon.jobs.qsize() == 1
    daemon._on_track("playing|Tycho|Awake|Epoch|sidra")  # resume same track -> fire
    daemon._on_track("playing|Tycho|Epoch|Epoch|sidra")  # next song, still playing -> fire
    assert daemon.jobs.qsize() == 3


def test_mpris_paused_states_never_capture(tmp_path):
    """Paused players do not fire: daemon startup while paused and a track
    switch while paused are not listening time (#5)."""
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config
    from heimdall.db import init_db

    daemon = CaptureDaemon(Config(data_dir=tmp_path))
    init_db(path=daemon.db_path)
    daemon._on_track("paused|Tycho|Awake|Epoch|sidra")   # startup while paused -> no
    daemon._on_track("paused|Tycho|Epoch|Epoch|sidra")   # skip while paused -> no
    assert daemon.jobs.qsize() == 0
    daemon._on_track("playing|Tycho|Epoch|Epoch|sidra")  # resume -> fire
    assert daemon.jobs.qsize() == 1


# ---- span computation ----

def test_compute_spans_consecutive_deltas():
    frames = [
        {"ts": 0, "window_class": "a", "window_title": "A"},
        {"ts": 10, "window_class": "b", "window_title": "B"},
        {"ts": 25, "window_class": "a", "window_title": "A"},
    ]
    spans = compute_spans(frames, end_ms=40)
    assert [(s.start_ms, s.end_ms, s.window_class) for s in spans] == [
        (0, 10, "a"), (10, 25, "b"), (25, 40, "a"),
    ]
    assert spans[0].minutes == 10 / 60_000
    # last span runs to the day end
    assert spans[-1].end_ms == 40


def test_compute_spans_sorts_and_skips_zero():
    frames = [
        {"ts": 20, "window_class": "b", "window_title": "B"},
        {"ts": 5, "window_class": "a", "window_title": "A"},
        {"ts": 5, "window_class": "c", "window_title": "C"},  # same ts: later one owns the span
    ]
    spans = compute_spans(frames, end_ms=30)
    assert [(s.window_class, s.start_ms, s.end_ms) for s in spans] == [
        ("c", 5, 20), ("b", 20, 30),
    ]


def test_track_playing_ms_exact():
    tracks = [
        {"ts": 0, "status": "playing"},
        {"ts": 100, "status": "paused"},
        {"ts": 200, "status": "playing"},
        {"ts": 250, "status": "paused"},
    ]
    assert track_playing_ms(tracks, 0, 1000) == 150
    # clips to the day window
    assert track_playing_ms(tracks, 50, 220) == 50 + 20
    # trailing play runs to end
    tracks2 = [{"ts": 10, "status": "playing"}]
    assert track_playing_ms(tracks2, 0, 90) == 80
    # no statuses -> 0
    assert track_playing_ms([{"ts": 10, "status": "x"}], 0, 100) == 0


def test_rules_minutes_splits_spans():
    spans = compute_spans([
        {"ts": 0, "window_class": "mpv", "window_title": "M"},
        {"ts": 10, "window_class": "firefox", "window_title": "Y"},
        {"ts": 20, "window_class": "sidra", "window_title": "S"},
    ], end_ms=40)
    settled, unclassified = rules_minutes(spans, {"mpv": "Movies", "sidra": "Music"})
    assert settled == {"Movies": 10, "Music": 20}
    assert [(s.window_class, s.minutes) for s in unclassified] == [("firefox", 10 / 60_000)]


def test_spans_to_table_groups_by_window():
    spans = compute_spans([
        {"ts": 0, "window_class": "code", "window_title": "x.py"},
        {"ts": 600_000, "window_class": "code", "window_title": "x.py"},
        {"ts": 1_200_000, "window_class": "code", "window_title": "y.py"},
    ], end_ms=3_000_000)
    table = spans_to_table(spans)
    by_title = {t["window_title"]: t["minutes"] for t in table}
    assert by_title["x.py"] == 20
    assert by_title["y.py"] == 30


# ---- a11y-first extraction (v2 #33) ----

def _content_bearing_tree():
    return [{
        "role": "application", "name": "Google Chrome", "text": "", "children": [
            {"role": "frame", "name": "page - Google Chrome", "text": "", "children": [
                {"role": "document web", "name": "", "text": "", "children": [
                    {"role": "heading", "name": "", "text": "Accessibility Test Page"},
                    {"role": "paragraph", "name": "", "text": "Hello world, the quick brown fox"},
                    {"role": "link", "name": "Example link", "text": ""},
                    {"role": "button", "name": "Click me 456", "text": ""},
                    {"role": "list item", "name": "", "text": "First item"},
                    {"role": "list item", "name": "", "text": "Second item 789"},
                ]},
            ]},
        ]},
    ]


def _blank_tree():
    """A shell-only tree (unflagged Chromium): no real content nodes."""
    return [{
        "role": "application", "name": "Google Chrome", "text": "", "children": [
            {"role": "frame", "name": "page - Google Chrome", "text": ""},
        ]},
    ]


class _FakeTools:
    """CaptureTools with an injectable a11y reader; no subprocess tools."""

    def __init__(self, reader):
        self.a11y_read = reader
        self.grim = lambda *a: b"jpeg"
        self.activewindow = lambda: {"class": "google-chrome", "title": "page",
                                     "workspace": {"id": 2, "name": "2"},
                                     "at": [0, 0], "size": [10, 10]}


def test_extract_worker_stores_a11y_when_content_bearing(tmp_path):
    """A content-bearing tree becomes a11y_text/a11y_json; no ocr_text is set."""
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config
    from heimdall.db import init_db

    daemon = CaptureDaemon(Config(data_dir=tmp_path), tools=_FakeTools(lambda c, t: _content_bearing_tree()))
    init_db(path=daemon.db_path)
    frame_id = daemon.db.insert_frame(dict(ts=1, monitor=0, workspace=2,
                                           window_class="google-chrome",
                                           window_title="page", fullscreen=0,
                                           trigger="activewindow", image_path="f.jpg",
                                           image_bytes=1, ocr_text=None, ocr_sec=None))
    daemon.extract_jobs.put((frame_id, "google-chrome", "page", b"jpeg"))
    daemon.extract_jobs.put(None)
    daemon._extract_worker()
    frame = daemon.db.get_frame(frame_id)
    assert frame["a11y_text"] == "Accessibility Test Page\nHello world, the quick brown fox\nExample link\nClick me 456\nFirst item\nSecond item 789"
    assert "document web" in frame["a11y_json"]
    assert frame["ocr_text"] is None
    assert frame["ocr_sec"] is None
    assert frame["ocr_engine"] is None


def test_extract_worker_null_text_when_a11y_blind(tmp_path):
    """kitty and other off-bus windows store NULL text; no OCR subprocess runs."""
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config
    from heimdall.db import init_db

    for reader in (lambda c, t: None, lambda c, t: _blank_tree()):
        daemon = CaptureDaemon(Config(data_dir=tmp_path), tools=_FakeTools(reader))
        init_db(path=daemon.db_path)
        frame_id = daemon.db.insert_frame(dict(ts=1, monitor=0, workspace=2,
                                               window_class="kitty", window_title="zsh",
                                               fullscreen=0, trigger="activewindow",
                                               image_path="f.jpg", image_bytes=1,
                                               ocr_text=None, ocr_sec=None))
        daemon.extract_jobs.put((frame_id, "kitty", "zsh", b"jpeg"))
        daemon.extract_jobs.put(None)
        daemon._extract_worker()
        frame = daemon.db.get_frame(frame_id)
        assert frame["a11y_text"] is None
        assert frame["a11y_json"] is None
        assert frame["ocr_text"] is None


def test_capture_worker_passes_window_meta_for_extraction(tmp_path):
    """The capture worker hands (frame_id, window_class, window_title, img) to
    the extraction queue so the a11y reader can find the right window."""
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config
    from heimdall.db import init_db

    seen = []
    tools = _FakeTools(lambda c, t: None)
    tools.activewindow = lambda: {"class": "code", "title": "x.py — heimdall",
                                  "workspace": {"id": 2, "name": "2"},
                                  "at": [0, 0], "size": [10, 10]}
    daemon = CaptureDaemon(Config(data_dir=tmp_path), tools=tools)
    init_db(path=daemon.db_path)
    daemon.jobs.put(("activewindow", 1))
    daemon.jobs.put(None)
    daemon._capture_worker()
    assert daemon.extract_jobs.qsize() == 1
    frame_id, cls, title, img = daemon.extract_jobs.get()
    assert cls == "code"
    assert title == "x.py — heimdall"
    assert img == b"jpeg"
    assert frame_id is not None


def test_tesseract_removed_from_tools():
    """The tesseract subprocess is retired: no ocr tool exists on the tools."""
    from heimdall.capture.daemon import CaptureTools

    tools = CaptureTools()
    assert not hasattr(tools, "ocr")
    assert not hasattr(tools, "_ocr")
