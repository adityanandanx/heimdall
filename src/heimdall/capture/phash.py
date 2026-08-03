"""Perceptual-hash change gate (ticket #34).

An aHash (average hash) over an 8x8 grayscale downscale is cheap and robust to
encode noise: two hashes differing by more than `changed`'s threshold mean the
frame content actually changed. Keyed per window_class so a keepalive capture
of an unchanged window skips re-extraction.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image


def phash(img: bytes) -> str | None:
    """64-bit aHash of an image as 16 hex chars; None on unreadable input."""
    try:
        with Image.open(BytesIO(img)) as src:
            gray = src.convert("L").resize((8, 8), Image.LANCZOS)
    except Exception:  # noqa: BLE001
        return None
    px = list(gray.tobytes())
    mean = sum(px) / len(px)
    bits = 0
    for v in px:
        bits = (bits << 1) | (1 if v > mean else 0)
    return f"{bits:016x}"


def changed(old: str | None, new: str | None, threshold: int = 10) -> bool:
    """True when two hashes differ by more than `threshold` bits.

    A missing hash counts as changed (first sighting always extracts).
    """
    if old is None or new is None:
        return True
    return bin(int(old, 16) ^ int(new, 16)).count("1") > threshold
