"""Perceptual-hash change gate (ticket #34): phash + threshold comparison.

The gate is per window_class and skips re-extraction on keepalive captures
whose frame is unchanged. `phash` must be deterministic and robust to
re-encoding; `changed` compares hashes against a Hamming-distance threshold.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from heimdall.capture.phash import changed, phash


def _img(draw_fn) -> bytes:
    im = Image.new("RGB", (400, 120), "white")
    draw_fn(ImageDraw.Draw(im))
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _black_square():
    return _img(lambda d: d.rectangle([100, 30, 300, 90], fill="black"))


def _small_square():
    return _img(lambda d: d.rectangle([100, 30, 110, 40], fill="black"))


def _full_black():
    return _img(lambda d: d.rectangle([0, 0, 399, 119], fill="black"))


def test_phash_deterministic_hex():
    h = phash(_black_square())
    assert h == phash(_black_square())
    assert isinstance(h, str)
    assert len(h) == 16  # 64 bits of hex


def test_phash_different_content_different_hash():
    assert phash(_black_square()) != phash(_small_square())


def test_phash_robust_to_reencode():
    """Same content re-saved as JPEG at q95 hashes identically (no false change)."""
    img = _black_square()
    buf = BytesIO()
    Image.open(BytesIO(img)).save(buf, format="JPEG", quality=95)
    assert phash(img) == phash(buf.getvalue())


def test_phash_unreadable_returns_none():
    assert phash(b"not an image") is None


def test_changed_same_hash_is_unchanged():
    h = phash(_black_square())
    assert changed(h, h) is False


def test_changed_reencoded_is_unchanged():
    img = _black_square()
    buf = BytesIO()
    Image.open(BytesIO(img)).save(buf, format="JPEG", quality=95)
    assert changed(phash(img), phash(buf.getvalue())) is False


def test_changed_very_different_is_changed():
    """The black square (17 bits from the small square in the 8x8 aHash) is a
    real content change: above the default threshold of 10."""
    assert changed(phash(_black_square()), phash(_small_square())) is True
    assert changed(phash(_black_square()), phash(_full_black())) is True


def test_changed_missing_hash_counts_as_changed():
    assert changed(None, "abc") is True
    assert changed("abc", None) is True


def test_changed_threshold_boundary():
    """`changed` fires only when the Hamming distance exceeds `threshold`."""
    zero = "0000000000000000"
    one_bit = "0000000000000001"
    ten_bits = "00000000000003ff"   # 0x3ff = 1023 = ten 1-bits
    eleven_bits = "00000000000007ff"  # 0x7ff = 2047 = eleven 1-bits
    assert changed(zero, zero, threshold=10) is False
    assert changed(zero, one_bit, threshold=10) is False
    assert changed(zero, ten_bits, threshold=10) is False   # 10 > 10 is false
    assert changed(zero, eleven_bits, threshold=10) is True
