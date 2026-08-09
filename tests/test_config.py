"""config.yaml parsing for capture.change_gate + window_class_merge (#34)."""

from __future__ import annotations

import yaml
import pytest

from heimdall.config import load_config


def _write(tmp_path, body: dict) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(body))
    return str(path)


def test_change_gate_and_merge_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, {"data_dir": str(tmp_path)}))
    assert cfg.capture.change_gate is True
    assert cfg.capture.window_class_merge == {}


def test_change_gate_and_merge_parse(tmp_path):
    cfg = load_config(_write(tmp_path, {
        "data_dir": str(tmp_path),
        "capture": {
            "change_gate": False,
            "window_class_merge": {"code": "ocr_also", "thunar": "ocr_also"},
        },
    }))
    assert cfg.capture.change_gate is False
    assert cfg.capture.window_class_merge == {"code": "ocr_also", "thunar": "ocr_also"}


def test_window_class_merge_non_dict_ignored(tmp_path):
    cfg = load_config(_write(tmp_path, {
        "data_dir": str(tmp_path),
        "capture": {"window_class_merge": "code"},
    }))
    assert cfg.capture.window_class_merge == {}


def test_unknown_capture_key_warns(tmp_path):
    with pytest.warns(UserWarning, match="unknown key capture.bogus"):
        load_config(_write(tmp_path, {
            "data_dir": str(tmp_path),
            "capture": {"bogus": 1},
        }))


def test_watch_media_resolver_defaults_to_extension(tmp_path):
    cfg = load_config(_write(tmp_path, {"data_dir": str(tmp_path)}))
    assert cfg.watch.media_resolver == "extension"


def test_watch_media_resolver_parses_cdp(tmp_path):
    cfg = load_config(_write(tmp_path, {
        "data_dir": str(tmp_path),
        "watch": {"media_resolver": "cdp"},
    }))
    assert cfg.watch.media_resolver == "cdp"


def test_watch_excluded_players_defaults_to_none(tmp_path):
    cfg = load_config(_write(tmp_path, {"data_dir": str(tmp_path)}))
    assert cfg.watch.excluded_players == []


def test_watch_excluded_players_parses(tmp_path):
    cfg = load_config(_write(tmp_path, {
        "data_dir": str(tmp_path),
        "watch": {"excluded_players": ["sidra", "spotify"]},
    }))
    assert cfg.watch.excluded_players == ["sidra", "spotify"]


def test_watch_excluded_players_non_list_ignored(tmp_path):
    cfg = load_config(_write(tmp_path, {
        "data_dir": str(tmp_path),
        "watch": {"excluded_players": "sidra"},
    }))
    assert cfg.watch.excluded_players == []


def test_asr_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, {"data_dir": str(tmp_path)}))
    assert cfg.asr.model == "small"
    assert cfg.asr.device == "cpu"
    assert cfg.asr.compute_type == "int8"


def test_asr_parses(tmp_path):
    cfg = load_config(_write(tmp_path, {
        "data_dir": str(tmp_path),
        "asr": {"model": "base", "device": "cuda", "compute_type": "float16"},
    }))
    assert cfg.asr.model == "base"
    assert cfg.asr.device == "cuda"
    assert cfg.asr.compute_type == "float16"
