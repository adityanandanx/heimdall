"""Secondary seam: capture event parsing, trigger classification, debounce,
dedupe + span-timing computation with crafted sequences."""

from __future__ import annotations

from io import BytesIO
from typing import Callable, Optional

import yaml
from PIL import Image, ImageDraw

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
from heimdall.capture.spans import (compute_spans, rules_minutes, session_wall_ms,
                                    spans_to_table, track_playing_ms)
from heimdall.settings import apply_write

from conftest import content_tree


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


# ---- manual capture (heimdall capture -> /capture -> capture.request) ----

def test_manual_capture_request_enqueues_job(tmp_path):
    """A fresh request file makes the daemon enqueue a `manual` capture."""
    import json
    import time
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config

    daemon = CaptureDaemon(Config(data_dir=tmp_path))
    daemon.manual_request.write_text(json.dumps(
        {"id": "abc", "ts": int(time.time() * 1000)}))
    daemon._check_manual()
    assert daemon._manual_pending is True
    assert daemon._manual_rid == "abc"
    assert daemon.jobs.qsize() == 1
    trigger, _ = daemon.jobs.get()
    assert trigger == "manual"


def test_manual_capture_ignores_stale_and_repeat_requests(tmp_path):
    import json
    import time
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config

    daemon = CaptureDaemon(Config(data_dir=tmp_path))
    daemon.manual_request.write_text(json.dumps(
        {"id": "stale", "ts": int(time.time() * 1000) - 60_000}))
    daemon._check_manual()
    assert daemon.jobs.qsize() == 0  # older than MANUAL_REQUEST_MAX_AGE_MS -> ignored

    daemon.manual_request.write_text(json.dumps(
        {"id": "dup", "ts": int(time.time() * 1000)}))
    daemon._check_manual()
    daemon._check_manual()
    assert daemon.jobs.qsize() == 1  # same id only enqueues once


def test_manual_capture_ack_does_not_refire_same_request(tmp_path):
    """The request file persists after ack; the daemon must not treat it as a
    fresh request on the next poll (the 0.5s re-fire storm)."""
    import json
    import time
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config

    daemon = CaptureDaemon(Config(data_dir=tmp_path))
    daemon.manual_request.write_text(json.dumps(
        {"id": "abc", "ts": int(time.time() * 1000)}))
    daemon._check_manual()
    assert daemon.jobs.qsize() == 1

    trigger, _ = daemon.jobs.get()
    daemon._manual_ack(status="ok", frame_id=7)
    ack = json.loads(daemon.manual_ack.read_text())
    assert ack == {"id": "abc", "status": "ok", "frame_id": 7, "detail": None}

    daemon._check_manual()
    daemon._check_manual()
    assert daemon.jobs.qsize() == 0  # same rid acked -> never re-enqueues

    daemon.manual_request.write_text(json.dumps(
        {"id": "next", "ts": int(time.time() * 1000)}))
    daemon._check_manual()
    assert daemon.jobs.qsize() == 1  # a *new* rid still fires


def test_manual_capture_worker_stores_frame_and_acks(tmp_path):
    """Full worker path: manual bypasses interval + duplicate gates and acks
    the frame id on capture.request's sibling capture.ack."""
    import json
    import threading
    from heimdall.capture.daemon import CaptureDaemon, CaptureTools
    from heimdall.config import Config
    from heimdall.db import init_db

    daemon = CaptureDaemon(Config(data_dir=tmp_path), tools=CaptureTools(
        activewindow=lambda: {"class": "kitty", "title": "manual test",
                              "at": [0, 0], "size": [640, 480], "monitor": 0,
                              "fullscreen": 0},
        grim=lambda x, y, w, h: b"\xff\xd8\xff\xe0jpeg",
    ))
    init_db(path=daemon.db_path)
    daemon._manual_rid = "rid-1"
    daemon._manual_pending = True
    daemon.jobs.put(("manual", 1))
    daemon.jobs.put(None)
    t = threading.Thread(target=daemon._capture_worker)
    t.start()
    t.join(timeout=5)

    ack = json.loads(daemon.manual_ack.read_text())
    assert ack["id"] == "rid-1"
    assert ack["status"] == "ok"
    assert ack["frame_id"] is not None
    frame = daemon.db.get_frame(ack["frame_id"])
    assert frame["window_class"] == "kitty" and frame["trigger"] == "manual"
    assert daemon._manual_pending is False


def test_manual_capture_worker_acks_error_on_missing_window(tmp_path):
    import json
    import threading
    from heimdall.capture.daemon import CaptureDaemon, CaptureTools
    from heimdall.config import Config

    daemon = CaptureDaemon(Config(data_dir=tmp_path), tools=CaptureTools(
        activewindow=lambda: None,
        grim=lambda x, y, w, h: b"jpeg",
    ))
    daemon._manual_rid = "rid-2"
    daemon._manual_pending = True
    daemon.jobs.put(("manual", 1))
    daemon.jobs.put(None)
    t = threading.Thread(target=daemon._capture_worker)
    t.start()
    t.join(timeout=5)

    ack = json.loads(daemon.manual_ack.read_text())
    assert ack == {"id": "rid-2", "status": "error", "frame_id": None,
                   "detail": "no active window found"}
    assert daemon._manual_pending is False


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


def test_session_wall_ms_categorizes_and_skips_live():
    """YouTube/Movies wall-while-playing minutes come from watch-sessions: local
    file:// sources are Movies, everything else YouTube; live rows contribute 0."""
    sessions = [
        {"ts_start": 0, "ts_end": 1_000_000, "live": 0,
         "media_source": "https://www.youtube.com/watch?v=x"},
        {"ts_start": 2_000_000, "ts_end": 3_000_000, "live": 0,
         "media_source": "file:///mnt/movies/Inception.mkv"},
        {"ts_start": 4_000_000, "ts_end": 5_000_000, "live": 1,
         "media_source": "file:///mnt/movies/other.mkv"},
    ]
    out = session_wall_ms(sessions, 0, 10_000_000)
    assert out["YouTube"] == 1_000_000
    assert out["Movies"] == 1_000_000
    assert out["YouTube"] + out["Movies"] == 2_000_000


def test_session_wall_ms_clips_to_day_window():
    sessions = [{"ts_start": -1_000_000, "ts_end": 6_000_000, "live": 0,
                 "media_source": "https://youtu.be/x"}]
    assert session_wall_ms(sessions, 0, 5_000_000)["YouTube"] == 5_000_000


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

def _blank_tree() -> list[dict]:
    """A shell-only tree (unflagged Chromium): no real content nodes."""
    return [{
        "role": "application", "name": "Google Chrome", "text": "", "children": [
            {"role": "frame", "name": "page - Google Chrome", "text": ""},
        ]},
    ]


class _FakeTools:
    """CaptureTools with an injectable a11y reader + rapid_ocr; no subprocess tools."""

    def __init__(self, reader: Optional[Callable[[str, str], Optional[list]]] = None,
                 rapid: Optional[Callable[[bytes], Optional[str]]] = None):
        self.a11y_read = reader if reader is not None else lambda c, t: None
        self.rapid_ocr = rapid if rapid is not None else lambda img: None
        self.grim = lambda *a: b"jpeg"
        self.activewindow = lambda: {"class": "google-chrome", "title": "page",
                                     "workspace": {"id": 2, "name": "2"},
                                     "at": [0, 0], "size": [10, 10]}


def _png() -> bytes:
    im = Image.new("RGB", (40, 20), "white")
    ImageDraw.Draw(im).rectangle([10, 4, 30, 16], fill="black")
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _small_png() -> bytes:
    """A genuinely different image from _png(): a tiny square only."""
    im = Image.new("RGB", (40, 20), "white")
    ImageDraw.Draw(im).rectangle([18, 8, 22, 12], fill="black")
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_extract_worker_stores_a11y_when_content_bearing(tmp_path):
    """A content-bearing tree becomes a11y_text/a11y_json; no ocr_text is set
    and RapidOCR is not run (routing: a11y wins, ticket #34)."""
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config
    from heimdall.db import init_db

    calls = []
    daemon = CaptureDaemon(Config(data_dir=tmp_path),
                           tools=_FakeTools(lambda c, t: content_tree(),
                                            rapid=lambda img: (calls.append(img), "nope")[1]))
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
    assert frame["a11y_text"] == (
        "Accessibility Test Page\nHello world, the quick brown fox\n"
        "Example link\nClick me 456\nFirst item\nSecond item 789"
    )
    assert "document web" in frame["a11y_json"]
    assert frame["ocr_text"] is None
    assert frame["ocr_sec"] is None
    assert frame["ocr_engine"] is None
    assert calls == []


def test_extract_worker_blind_auto_uses_rapidocr(tmp_path):
    """A blind window (kitty) in auto mode stores a11y NULL + RapidOCR text
    with ocr_engine='rapid' (the #34 fallback replaces the NULL gap)."""
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config
    from heimdall.db import init_db

    for reader in (lambda c, t: None, lambda c, t: _blank_tree()):
        calls = []
        tools = _FakeTools(reader, rapid=lambda img: (calls.append(img), "fallback text")[1])
        daemon = CaptureDaemon(Config(data_dir=tmp_path), tools=tools)
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
        assert frame["ocr_text"] == "fallback text"
        assert frame["ocr_engine"] == "rapid"
        assert calls == [b"jpeg"]


def test_extract_worker_merge_class_stores_both(tmp_path):
    """A window_class in capture.window_class_merge (ocr_also) stores a11y_text
    AND ocr_text, even when the a11y tree is content-bearing."""
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config
    from heimdall.db import init_db

    cfg = Config(data_dir=tmp_path)
    cfg.capture.window_class_merge = {"code": "ocr_also"}
    daemon = CaptureDaemon(cfg, tools=_FakeTools(
        lambda c, t: content_tree(), rapid=lambda img: "ocr-side text"))
    init_db(path=daemon.db_path)
    frame_id = daemon.db.insert_frame(dict(ts=1, monitor=0, workspace=2,
                                           window_class="code", window_title="x.py",
                                           fullscreen=0, trigger="activewindow",
                                           image_path="f.jpg", image_bytes=1,
                                           ocr_text=None, ocr_sec=None))
    daemon.extract_jobs.put((frame_id, "code", "x.py", b"jpeg"))
    daemon.extract_jobs.put(None)
    daemon._extract_worker()
    frame = daemon.db.get_frame(frame_id)
    assert "Accessibility Test Page" in frame["a11y_text"]
    assert frame["a11y_json"] is not None
    assert frame["ocr_text"] == "ocr-side text"
    assert frame["ocr_engine"] == "rapid"


def test_extract_worker_merge_class_blind_still_runs_ocr(tmp_path):
    """A merge class that is a11y-blind still gets RapidOCR text (a11y NULL)."""
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config
    from heimdall.db import init_db

    cfg = Config(data_dir=tmp_path)
    cfg.capture.window_class_merge = {"thunar": "ocr_also"}
    daemon = CaptureDaemon(cfg, tools=_FakeTools(
        lambda c, t: None, rapid=lambda img: "file manager"))
    init_db(path=daemon.db_path)
    frame_id = daemon.db.insert_frame(dict(ts=1, monitor=0, workspace=2,
                                           window_class="thunar", window_title="~",
                                           fullscreen=0, trigger="activewindow",
                                           image_path="f.jpg", image_bytes=1,
                                           ocr_text=None, ocr_sec=None))
    daemon.extract_jobs.put((frame_id, "thunar", "~", b"jpeg"))
    daemon.extract_jobs.put(None)
    daemon._extract_worker()
    frame = daemon.db.get_frame(frame_id)
    assert frame["a11y_text"] is None
    assert frame["ocr_text"] == "file manager"
    assert frame["ocr_engine"] == "rapid"


def test_extract_worker_ocr_mode_uses_rapid_only(tmp_path):
    """capture.extraction='ocr' stores RapidOCR text and leaves a11y untouched,
    even when the tree would have been content-bearing."""
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config
    from heimdall.db import init_db

    cfg = Config(data_dir=tmp_path)
    cfg.capture.extraction = "ocr"
    calls = []
    daemon = CaptureDaemon(cfg, tools=_FakeTools(
        lambda c, t: content_tree(), rapid=lambda img: (calls.append(img), "ocr text")[1]))
    init_db(path=daemon.db_path)
    frame_id = daemon.db.insert_frame(dict(ts=1, monitor=0, workspace=2,
                                           window_class="firefox", window_title="page",
                                           fullscreen=0, trigger="activewindow",
                                           image_path="f.jpg", image_bytes=1,
                                           ocr_text=None, ocr_sec=None))
    daemon.extract_jobs.put((frame_id, "firefox", "page", b"jpeg"))
    daemon.extract_jobs.put(None)
    daemon._extract_worker()
    frame = daemon.db.get_frame(frame_id)
    assert frame["a11y_text"] is None
    assert frame["ocr_text"] == "ocr text"
    assert frame["ocr_engine"] == "rapid"
    assert calls == [b"jpeg"]


def test_extract_worker_a11y_mode_blind_stores_nothing(tmp_path):
    """capture.extraction='a11y' never runs RapidOCR, even on blind windows."""
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config
    from heimdall.db import init_db

    cfg = Config(data_dir=tmp_path)
    cfg.capture.extraction = "a11y"
    calls = []
    daemon = CaptureDaemon(cfg, tools=_FakeTools(
        lambda c, t: None, rapid=lambda img: (calls.append(img), "x")[1]))
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
    assert frame["ocr_text"] is None
    assert calls == []


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


def test_excluded_window_gate_skips_auto_but_manual_bypasses(tmp_path):
    """watch.excluded_windows skips scheduled captures for that window class,
    but a manual capture always fires (#72, trigger gate: no frame ever
    stored for an excluded window on auto triggers)."""
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config
    from heimdall.db import init_db

    cfg = Config(data_dir=tmp_path)
    cfg.watch.excluded_windows = ["steam"]
    tools = _FakeTools(lambda c, t: None)
    tools.activewindow = lambda: {"class": "steam", "title": "Steam",
                                  "workspace": {"id": 1, "name": "1"},
                                  "at": [0, 0], "size": [10, 10]}
    daemon = CaptureDaemon(cfg, tools=tools)
    init_db(path=daemon.db_path)

    daemon.jobs.put(("activewindow", 1))  # auto: gated
    daemon.jobs.put(("manual", 2))        # manual: bypasses the gate
    daemon.jobs.put(None)
    daemon._capture_worker()

    total, _ = daemon.db.list_frames(limit=10)
    assert total == 1  # only the manual frame stored


def test_daemon_reload_swaps_excluded_windows_and_media_resolver(tmp_path):
    """The dirty-marker reload must pick up the exclusion list and the media
    resolver swap live, not only on restart (#72, #74)."""
    from heimdall.capture.daemon import CaptureDaemon, CaptureTools
    from heimdall.config import load_config

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "data_dir": str(tmp_path),
        "watch": {"excluded_windows": ["steam"], "media_resolver": "extension"},
    }))
    daemon = CaptureDaemon(
        load_config(str(cfg_path)),
        tools=CaptureTools(captions_dir=tmp_path),
        db_path=tmp_path / "db.sqlite",
        config_path=str(cfg_path),
    )
    assert daemon._excluded_windows == {"steam"}
    assert daemon.tools.media_resolver == "extension"

    apply_write(cfg_path, "watch.excluded_windows", ["steam", "vlc"],
                dirty_path=tmp_path / "settings.dirty")
    apply_write(cfg_path, "watch.media_resolver", "cdp",
                dirty_path=tmp_path / "settings.dirty")
    daemon._reload_config_if_dirty()

    assert daemon._excluded_windows == {"steam", "vlc"}
    assert daemon.tools.media_resolver == "cdp"


def test_daemon_publishes_active_engine_file(tmp_path):
    """The daemon writes data/capture.engine with the engine it actually
    resolved (npu/cpu), which /status reads for the active/configured split
    (#71); a failed NPU install falls back to cpu without crashing."""
    from heimdall.capture.daemon import CaptureDaemon, CaptureTools
    from heimdall.config import load_config

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "data_dir": str(tmp_path),
        "capture": {"ocr_engine": "auto"},
    }))
    daemon = CaptureDaemon(
        load_config(str(cfg_path)),
        tools=CaptureTools(captions_dir=tmp_path),
        db_path=tmp_path / "db.sqlite",
        config_path=str(cfg_path),
    )
    daemon._publish_engine()
    engine = (tmp_path / "capture.engine").read_text()
    assert engine in ("cpu", "npu")  # whatever is installed locally
    assert daemon.engine_file == tmp_path / "capture.engine"


# ---- per-window perceptual-hash change gate (ticket #34) ----

def _gate_daemon(tmp_path, titles=None, images=None):
    """A daemon wired for change-gate tests: real PNGs from grim so phash works,
    per-job window titles (lazily consumed, so jobs aren't signature-duplicate)
    and no min-interval throttle so back-to-back jobs both run."""
    from heimdall.capture.daemon import CaptureDaemon
    from heimdall.config import Config
    from heimdall.db import init_db

    cfg = Config(data_dir=tmp_path)
    cfg.capture.min_interval_s = 0
    titles = iter(titles or ["zsh — htop", "zsh — pacman"])
    images = iter(images or [_png(), _png()])
    tools = _FakeTools(reader=None, rapid=lambda img: "re-extracted")
    tools.grim = lambda *a: next(images)
    tools.activewindow = lambda: {"class": "kitty", "title": next(titles),
                                  "workspace": {"id": 1, "name": "1"},
                                  "at": [0, 0], "size": [40, 20]}
    daemon = CaptureDaemon(cfg, tools=tools)
    init_db(path=daemon.db_path)
    return daemon


def test_change_gate_skips_unchanged_keepalive(tmp_path):
    """A keepalive capture whose pixels are unchanged for the window is stored
    but not re-extracted; the change-gate skips the extract job."""
    daemon = _gate_daemon(tmp_path)
    daemon.jobs.put(("keepalive", 1))
    daemon.jobs.put(("keepalive", 2))
    daemon.jobs.put(None)
    daemon._capture_worker()

    total, frames = daemon.db.list_frames(limit=10)
    assert total == 2                    # both frames stored
    assert daemon.extract_jobs.qsize() == 1  # only the first was extracted


def test_keepalive_bypasses_signature_dedupe(tmp_path):
    """The same window must still be sampled on the keepalive cadence: the
    signature-dedupe gate applies to event pulses only, so a static page
    (same class+title+workspace) keeps accumulating frames. The phash change
    gate still skips re-extraction of the unchanged window."""
    daemon = _gate_daemon(tmp_path, titles=["zsh — htop", "zsh — htop"])
    daemon.config.capture.change_gate = False  # isolate the dedupe interaction
    daemon.jobs.put(("keepalive", 1))
    daemon.jobs.put(("keepalive", 2))
    daemon.jobs.put(None)
    daemon._capture_worker()

    total, frames = daemon.db.list_frames(limit=10)
    assert total == 2


def test_event_pulses_burst_are_deduped(tmp_path):
    """Event pulses with an unchanged signature are dropped even on a
    keepalive cadence — a pulse burst after an identical keepalive frame must
    not store duplicates."""
    daemon = _gate_daemon(tmp_path, titles=["zsh — htop", "zsh — htop", "zsh — htop"])
    daemon.config.capture.change_gate = False
    daemon.jobs.put(("keepalive", 1))
    daemon.jobs.put(("activewindow", 2))   # same signature -> deduped
    daemon.jobs.put(("activewindow", 3))   # same signature -> deduped
    daemon.jobs.put(None)
    daemon._capture_worker()

    total, _ = daemon.db.list_frames(limit=10)
    assert total == 1


def test_change_gate_event_trigger_re_extracts(tmp_path):
    """The next event-triggered capture re-extracts even for unchanged pixels
    (the gate only applies to keepalive triggers)."""
    daemon = _gate_daemon(tmp_path, ["t1", "t2", "t3"], [_png(), _png(), _png()])
    daemon.jobs.put(("keepalive", 1))
    daemon.jobs.put(("keepalive", 2))   # stored, gate skips re-extraction
    daemon.jobs.put(("activewindow", 3))  # event trigger always extracts
    daemon.jobs.put(None)
    daemon._capture_worker()

    total, _ = daemon.db.list_frames(limit=10)
    assert total == 3
    assert daemon.extract_jobs.qsize() == 2


def test_change_gate_changed_pixels_re_extracts(tmp_path):
    """A keepalive capture whose pixels actually changed is extracted."""
    daemon = _gate_daemon(tmp_path, images=[_png(), _small_png()])
    daemon.jobs.put(("keepalive", 1))
    daemon.jobs.put(("keepalive", 2))
    daemon.jobs.put(None)
    daemon._capture_worker()

    total, _ = daemon.db.list_frames(limit=10)
    assert total == 2
    assert daemon.extract_jobs.qsize() == 2


def test_change_gate_disabled_always_extracts(tmp_path):
    """capture.change_gate=false disables the gate: unchanged keepalive frames
    are still re-extracted."""
    daemon = _gate_daemon(tmp_path)
    daemon.config.capture.change_gate = False
    daemon.jobs.put(("keepalive", 1))
    daemon.jobs.put(("keepalive", 2))
    daemon.jobs.put(None)
    daemon._capture_worker()

    total, _ = daemon.db.list_frames(limit=10)
    assert total == 2
    assert daemon.extract_jobs.qsize() == 2
