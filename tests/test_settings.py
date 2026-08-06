"""Live settings write-through (#70): config round-trip, daemon reload, API.

The desktop app writes user-owned settings into heimdall's own config.yaml via
dotted keys; the daemon polls the settings.dirty marker and swaps its config.
"""

from __future__ import annotations

import time
import yaml

from heimdall.settings import apply_write, get_value, load_raw, touch_dirty, validate_key


def _cfg(tmp_path, extra=None):
    cfg = tmp_path / "config.yaml"
    body = {"data_dir": str(tmp_path), "capture": {"extraction": True, "ocr_engine": "cpu"}}
    if extra:
        body.update(extra)
    cfg.write_text(yaml.safe_dump(body))
    return cfg


def test_apply_write_sets_dotted_key_and_preserves_unknowns(tmp_path):
    cfg = _cfg(tmp_path, extra={"hand_edited": {"keep": [1, 2, 3]}})
    apply_write(cfg, "capture.ocr_engine", "npu", dirty_path=tmp_path / "settings.dirty")
    after = load_raw(cfg)
    assert after["capture"]["ocr_engine"] == "npu"
    assert after["capture"]["extraction"] is True
    assert after["hand_edited"] == {"keep": [1, 2, 3]}
    assert (tmp_path / "settings.dirty").exists()


def test_apply_write_creates_missing_sections(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("")
    apply_write(cfg, "scheduler.day_recap", False, dirty_path=tmp_path / "settings.dirty")
    assert load_raw(cfg)["scheduler"]["day_recap"] is False


def test_validate_key_rejects_unknown_and_bad_values(tmp_path):
    assert validate_key("capture.ocr_engine", "npu") is None
    assert "not a writable setting" in validate_key("capture.bogus", 1)
    assert "cpu|npu|auto" in validate_key("capture.ocr_engine", "gpu")
    assert "boolean" in validate_key("capture.paused", "yes")


def test_apply_write_refuses_unwritable_and_null(tmp_path):
    cfg = _cfg(tmp_path)
    from heimdall.settings import UnknownSettingError

    try:
        apply_write(cfg, "capture.bogus", 1)
        raise AssertionError("expected UnknownSettingError")
    except UnknownSettingError:
        pass
    try:
        apply_write(cfg, "capture.paused", None)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    assert load_raw(cfg)["capture"]["ocr_engine"] == "cpu"


def test_daemon_reloads_config_via_dirty_marker(tmp_path):
    from heimdall.capture.daemon import CaptureDaemon, CaptureTools
    from heimdall.config import load_config

    cfg = _cfg(tmp_path, extra={"watch": {"excluded_players": ["spotify"]}})
    daemon = CaptureDaemon(
        load_config(str(cfg)),
        tools=CaptureTools(captions_dir=tmp_path),
        db_path=tmp_path / "db.sqlite",
        config_path=str(cfg),
    )
    assert daemon.tools.ocr_engine == "cpu"
    assert daemon._excluded_players == {"spotify"}

    apply_write(cfg, "capture.ocr_engine", "npu", dirty_path=tmp_path / "settings.dirty")
    apply_write(cfg, "capture.paused", True, dirty_path=tmp_path / "settings.dirty")
    apply_write(cfg, "watch.excluded_players", ["spotify", "vlc"],
                dirty_path=tmp_path / "settings.dirty")

    daemon._reload_config_if_dirty()
    assert daemon.tools.ocr_engine == "npu"
    assert daemon.config.capture.paused is True
    assert daemon._excluded_players == {"spotify", "vlc"}

    # marker unchanged -> no-op (no churn on every heartbeat tick)
    daemon._reload_config_if_dirty()
    assert daemon.tools.ocr_engine == "npu"


def test_daemon_keeps_previous_config_on_bad_reload(tmp_path):
    from heimdall.capture.daemon import CaptureDaemon, CaptureTools
    from heimdall.config import load_config

    cfg = _cfg(tmp_path, extra={"capture": {"paused": True}})
    daemon = CaptureDaemon(
        load_config(str(cfg)),
        tools=CaptureTools(captions_dir=tmp_path),
        db_path=tmp_path / "db.sqlite",
        config_path=str(cfg),
    )
    apply_write(cfg, "capture.ocr_engine", "npu", dirty_path=tmp_path / "settings.dirty")
    cfg.write_text("capture: [broken")
    daemon._reload_config_if_dirty()
    assert daemon.config.capture.paused is True  # pre-bad-write value kept


def test_paused_gate_skips_capture_jobs(tmp_path):
    from heimdall.capture.daemon import CaptureDaemon, CaptureTools
    from heimdall.config import load_config

    cfg = _cfg(tmp_path)
    cfg.write_text(yaml.safe_dump({"data_dir": str(tmp_path),
                                   "capture": {"paused": True, "min_interval_s": 1}}))
    daemon = CaptureDaemon(
        load_config(str(cfg)),
        tools=CaptureTools(captions_dir=tmp_path),
        db_path=tmp_path / "db.sqlite",
        config_path=str(cfg),
    )
    acks = []
    daemon._manual_ack = lambda **kw: acks.append(kw)
    daemon.jobs.put(("keepalive", 1))
    daemon.jobs.put(None)  # sentinel: worker exits

    import threading

    t = threading.Thread(target=daemon._capture_worker, daemon=True)
    t.start()
    t.join(timeout=5)
    assert not t.is_alive()
    assert acks == []  # keepalive silently skipped while paused


def test_settings_endpoint_writes_through_and_dirty(tmp_path):
    from fastapi.testclient import TestClient

    from heimdall.api.app import create_app
    from heimdall.config import load_config

    cfg = _cfg(tmp_path)
    app = create_app(load_config(str(cfg)), config_path=str(cfg))
    client = TestClient(app)

    r = client.post("/settings", json={"key": "capture.ocr_engine", "value": "npu"})
    assert r.status_code == 200, r.text
    assert r.json()["value"] == "npu"
    assert load_raw(cfg)["capture"]["ocr_engine"] == "npu"
    assert (tmp_path / "settings.dirty").exists()
    # status reflects the new engine
    assert client.get("/status").json()["capture"]["ocr_engine"] == "npu"


def test_settings_endpoint_rejects_bad_key_and_no_config_path(tmp_path):
    from fastapi.testclient import TestClient

    from heimdall.api.app import create_app
    from heimdall.config import load_config

    cfg = _cfg(tmp_path)
    app = create_app(load_config(str(cfg)), config_path=str(cfg))
    client = TestClient(app)
    assert client.post("/settings", json={"key": "capture.bogus", "value": 1}).status_code == 422
    assert client.post("/settings", json={"key": "capture.ocr_engine", "value": "gpu"}).status_code == 422
    # embedded mode (no config_path): write refused, not silently dropped
    app2 = create_app(load_config(str(cfg)))
    client2 = TestClient(app2)
    assert client2.post("/settings", json={"key": "capture.ocr_engine", "value": "cpu"}).status_code == 500
