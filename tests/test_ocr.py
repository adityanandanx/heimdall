"""OCR fallback routing + lazy engine seam (ticket #34).

`route_extraction` is the pure source decision behind the extraction worker:
a11y wins in auto mode, blind windows fall back to RapidOCR, and classes in
`window_class_merge` store both. `rapid_ocr` must degrade to None (not crash)
when the package is absent.
"""

from __future__ import annotations

import builtins
import io
import logging

from heimdall.capture import ocr as ocr_mod
from heimdall.capture.ocr import rapid_ocr, route_extraction

MERGE = {"code": "ocr_also", "thunar": "ocr_also"}


# ---- routing decision ----

def test_route_ocr_mode_always_rapid():
    assert route_extraction("ocr", True, "code", MERGE) == "ocr"
    assert route_extraction("ocr", False, "kitty", MERGE) == "ocr"
    assert route_extraction("ocr", True, "firefox", None) == "ocr"


def test_route_a11y_mode_content_bearing():
    assert route_extraction("a11y", True, "firefox", MERGE) == "a11y"
    assert route_extraction("a11y", True, None, None) == "a11y"


def test_route_a11y_mode_blind_stores_nothing():
    assert route_extraction("a11y", False, "kitty", MERGE) == "none"


def test_route_auto_a11y_wins_on_content_bearing():
    assert route_extraction("auto", True, "firefox", MERGE) == "a11y"
    assert route_extraction("auto", True, None, None) == "a11y"


def test_route_auto_blind_falls_back_to_ocr():
    assert route_extraction("auto", False, "kitty", MERGE) == "ocr"
    assert route_extraction("auto", False, "kitty", None) == "ocr"


def test_route_auto_merge_class_stores_both():
    """window_class_merge (ocr_also) overrides the a11y-wins default in auto."""
    assert route_extraction("auto", True, "code", MERGE) == "both"
    assert route_extraction("auto", False, "code", MERGE) == "both"


def test_route_merge_map_missing_or_empty_is_no_override():
    assert route_extraction("auto", True, "code", None) == "a11y"
    assert route_extraction("auto", False, "code", {}) == "ocr"


# ---- rapid_ocr degradation seam ----

def test_rapid_ocr_missing_package_returns_none_and_warns_once(monkeypatch):
    """No rapidocr -> None (daemon keeps running), logged only the first time."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "rapidocr":
            raise ImportError("no rapidocr installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(ocr_mod, "_engine", None)
    monkeypatch.setattr(ocr_mod, "_missing_logged", False)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("heimdall.capture")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        assert rapid_ocr(b"jpeg") is None
        assert rapid_ocr(b"jpeg") is None
    finally:
        logger.removeHandler(handler)

    assert stream.getvalue().count("rapidocr not installed") == 1
    assert ocr_mod._engine is None
