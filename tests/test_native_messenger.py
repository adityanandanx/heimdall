"""Native-messaging host protocol (v2 #44).

The extension's background worker opens a native port; the host reads
length-prefixed frames from stdin, forwards ``{title, href, currentTimeUs}``
to the API, and acks on stdout. These tests drive the protocol with injected
streams + an httpx MockTransport so no browser or real API is needed.
"""

from __future__ import annotations

import io
import json
import struct

import httpx

from heimdall import native_messenger

YT_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _frame(obj) -> bytes:
    data = json.dumps(obj).encode("utf-8")
    return struct.pack("=I", len(data)) + data


def _run(payload: bytes, transport=None) -> tuple[int, str, list[dict]]:
    stdin = io.BytesIO(payload)
    stdout = io.BytesIO()
    code = native_messenger.run(stdin=stdin, stdout=stdout, transport=transport)
    return code, stdout.getvalue().decode(), _parse_frames(stdout.getvalue())


def _parse_frames(raw: bytes) -> list[dict]:
    frames = []
    buf = io.BytesIO(raw)
    while True:
        frame = native_messenger.read_frame(buf)
        if frame is None:
            break
        frames.append(json.loads(frame))
    return frames


def test_frame_roundtrip():
    payload = b""
    for obj in ({"a": 1}, {"b": "x"}):
        payload += _frame(obj)
    stdin = io.BytesIO(payload)
    out = io.BytesIO()
    for obj in ({"a": 1}, {"b": "x"}):
        assert native_messenger.read_frame(stdin) == json.dumps(obj).encode()
    native_messenger.write_frame(out, {"ok": True})
    assert _parse_frames(out.getvalue()) == [{"ok": True}]


def _capture_transport():
    hits = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handler), hits


def test_run_forwards_frame_to_api():
    transport, hits = _capture_transport()
    code, _, acks = _run(_frame({
        "title": "Rick Astley - Never Gonna Give You Up - YouTube",
        "href": YT_URL,
        "currentTimeUs": 900_000_000,
    }) + _frame({
        "title": "Other tab",
        "href": "https://example.com/x",
        "currentTimeUs": 12,
    }), transport)
    assert code == 0
    assert hits == [
        {"title": "Rick Astley - Never Gonna Give You Up - YouTube",
         "href": YT_URL, "current_time_us": 900_000_000},
        {"title": "Other tab", "href": "https://example.com/x",
         "current_time_us": 12},
    ]
    assert acks == [{"ok": True}, {"ok": True}]


def test_run_api_down_acks_error_and_keeps_going():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    code, _, acks = _run(_frame({"title": "x", "href": YT_URL}) + _frame({"title": "y", "href": YT_URL}),
                         httpx.MockTransport(handler))
    assert code == 0
    assert len(acks) == 2
    assert all(not a["ok"] and a["error"] for a in acks)


def test_run_bad_json_acks_error():
    transport, hits = _capture_transport()
    bad = struct.pack("=I", len(b"garbage")) + b"garbage"
    code, _, acks = _run(bad, transport)
    assert code == 0
    assert acks == [{"ok": False, "error": "bad json"}]
    assert hits == []


def test_run_missing_href_acks_error():
    transport, hits = _capture_transport()
    code, _, acks = _run(_frame({"title": "x"}), transport)
    assert code == 0
    assert acks == [{"ok": False, "error": "missing href"}]
    assert hits == []


def test_run_truncated_payload_returns_nonzero():
    stdin = io.BytesIO(struct.pack("=I", 100) + b"short")
    code = native_messenger.run(stdin=stdin, stdout=io.BytesIO())
    assert code == 1


def test_run_clean_eof_returns_zero():
    code = native_messenger.run(stdin=io.BytesIO(b""), stdout=io.BytesIO())
    assert code == 0
