"""RapidOCR fallback + extraction routing (ticket #34).

`rapid_ocr` runs RapidOCR (onnxruntime) over a frame image in the extraction
worker; `route_extraction` is the pure decision of which source(s) win for a
window. Both sit behind the same worker seam as the a11y reader, so a missing
package or a routing change never crashes the daemon.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("heimdall.capture")

# Engine registry: keyed by the `capture.ocr_engine` value, so a live config
# flip rebuilds the right engine on next use. `_engine_key` tracks which one
# `_engine` was built for; a mismatch means the setting changed mid-session.
_engine: object | None = None
_engine_key: str | None = None
_active_engine: str | None = None  # resolved npu|cpu after a build, for /status (#71)
_missing_logged = False

# OCR is a background fallback; cap onnxruntime's thread pool so the extraction
# worker stops pinning every core (heat/battery). Breaks no perf contract: the
# queue never blocks a capture, so per-frame latency is not user-visible.
_ORT_THREAD_PARAMS = {
    "EngineConfig.onnxruntime.intra_op_num_threads": 2,
    "EngineConfig.onnxruntime.inter_op_num_threads": 1,
}


def _build_engine(engine: str) -> object:
    """Build the engine for a `capture.ocr_engine` value; None if unavailable.

    "npu" routes rapidocr's det/cls/rec factories to the OpenVINO NPU session
    (`npu_ocr`); "auto" tries NPU first and degrades to CPU when the NPU can't
    be used; "cpu" always uses onnxruntime with capped threads. Any engine that
    fails to init degrades to the CPU engine, never None.
    """
    from rapidocr import RapidOCR

    params = dict(_ORT_THREAD_PARAMS)
    global _active_engine
    if engine in ("auto", "npu"):
        from heimdall.capture import npu_ocr

        if npu_ocr.install_npu_engine():
            _active_engine = "npu"
            return RapidOCR(params=params)
    else:
        from heimdall.capture import npu_ocr

        # a live flip back to cpu must undo the process-global NPU route,
        # and then match the same capped thread setup
        npu_ocr.uninstall_npu_engine()
    _active_engine = "cpu"
    return RapidOCR(params=params)


def active_engine() -> str | None:
    """The resolved engine (npu|cpu) after the last build; None before any
    build. The daemon publishes this so /status can distinguish the configured
    value from what actually runs (#71)."""
    return _active_engine


def rapid_ocr(img: bytes, engine: str = "auto") -> Optional[str]:
    """Recognize text in a frame image; None on error or no text.

    The engine is lazily imported and initialized the first time so a machine
    without rapidocr degrades to None (the daemon keeps running, like a
    missing playerctl) instead of failing at startup. `engine` is the live
    `capture.ocr_engine` value; a change between calls rebuilds the singleton.
    """
    global _engine, _engine_key, _missing_logged
    if engine not in ("cpu", "npu", "auto"):
        log.warning("unknown ocr_engine %r, treating as auto", engine)
        engine = "auto"
    if _engine is None or _engine_key != engine:
        try:
            from rapidocr import RapidOCR
        except ImportError:
            if not _missing_logged:
                log.warning("rapidocr not installed; OCR fallback disabled")
                _missing_logged = True
            _engine = None
            _engine_key = engine
            return None
        try:
            _engine = _build_engine(engine)
            _engine_key = engine
        except Exception as exc:  # noqa: BLE001
            if not _missing_logged:
                log.warning("rapidocr init failed; OCR fallback disabled: %s", exc)
                _missing_logged = True
            _engine = None
            _engine_key = engine
            return None
    try:
        result = _engine(img)
    except Exception as exc:  # noqa: BLE001
        log.warning("rapidocr inference failed: %s", exc)
        return None
    texts = getattr(result, "txts", None)
    if not texts:
        return None
    return "\n".join(texts)


def route_extraction(
    mode: str,
    content_bearing: bool,
    window_class: str,
    merge_map: Optional[dict[str, str]] = None,
) -> str:
    """Which source(s) should extract a frame: "a11y" | "ocr" | "both" | "none".

    - "ocr" mode: RapidOCR always.
    - "a11y" mode: a11y when the tree has content, else nothing (never OCR).
    - "auto": a11y wins on content-bearing windows; blind windows fall back to
      RapidOCR. A class in `merge_map` (capture.window_class_merge, e.g.
      ocr_also) stores both sources regardless of the content-bearing test.
    """
    merge_map = merge_map or {}
    also_ocr = window_class in merge_map
    if mode == "ocr":
        return "ocr"
    if content_bearing:
        return "both" if also_ocr else "a11y"
    if mode == "a11y":
        return "none"
    return "both" if also_ocr else "ocr"
