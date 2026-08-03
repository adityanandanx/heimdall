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

_engine: object | None = None
_missing_logged = False


def rapid_ocr(img: bytes) -> Optional[str]:
    """Recognize text in a frame image; None on error or no text.

    The engine is lazily imported and initialized the first time so a machine
    without rapidocr degrades to None (the daemon keeps running, like a
    missing playerctl) instead of failing at startup.
    """
    global _engine, _missing_logged
    if _engine is None:
        try:
            from rapidocr import RapidOCR
        except ImportError:
            if not _missing_logged:
                log.warning("rapidocr not installed; OCR fallback disabled")
                _missing_logged = True
            return None
        try:
            _engine = RapidOCR()
        except Exception as exc:  # noqa: BLE001
            if not _missing_logged:
                log.warning("rapidocr init failed; OCR fallback disabled: %s", exc)
                _missing_logged = True
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
