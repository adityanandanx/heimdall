"""Native-messaging host for the heimdall extension (v2 #44).

Reads length-prefixed JSON frames from stdin (the Chrome native-messaging
protocol), forwards each ``{title, href, currentTimeUs}`` reading to the API's
``POST /media/live`` endpoint, and acks on stdout so the port stays open.
Fail-soft: a dead API, bad JSON, or a frame error is logged to stderr and
acked as an error — never fatal to the browser or the daemon.

Run by the browser via ``-m heimdall.native_messenger`` (see the installed
NativeMessagingHosts manifest). Debug output goes to stderr only: stdout is
the protocol.
"""

from __future__ import annotations

import json
import logging
import struct
import sys
from typing import Optional

log = logging.getLogger("heimdall.native_messenger")

_DEFAULT_PORT = 3931
_FRAME_SIZE = struct.Struct("=I")


def read_frame(stream) -> Optional[bytes]:
    """One length-prefixed native-messaging frame, or None on clean EOF.

    Raises OSError when stdin closes mid-frame (browser killed us).
    """
    header = stream.read(4)
    if not header:
        return None
    if len(header) < 4:
        raise OSError("truncated length header")
    (size,) = _FRAME_SIZE.unpack(header)
    payload = stream.read(size)
    if len(payload) < size:
        raise OSError("truncated message payload")
    return payload


def write_frame(stream, obj) -> None:
    """Emit one length-prefixed frame; only call with protocol data."""
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    stream.write(_FRAME_SIZE.pack(len(data)) + data)
    stream.flush()


def api_url() -> str:
    """Base URL of the heimdall API, from config (defaults to 3931)."""
    try:
        from heimdall.config import load_config

        cfg = load_config()
        base = cfg.api.bind
        if base in ("0.0.0.0", "::"):
            base = "127.0.0.1"
        return f"http://{base}:{cfg.api.port}"
    except Exception:  # noqa: BLE001
        return f"http://127.0.0.1:{_DEFAULT_PORT}"


def run(*, stdin=None, stdout=None, transport=None) -> int:
    """Serve frames until the browser closes stdin; returns the exit code.

    `stdin`/`stdout`/`transport` are injectable so tests drive the protocol
    without a browser. Returns 0 on a clean EOF and 1 on a protocol error.
    """
    import httpx

    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    timeout = httpx.Timeout(2.0, connect=1.0)
    client = httpx.Client(base_url=api_url(), timeout=timeout,
                          transport=transport or httpx.HTTPTransport())
    try:
        while True:
            try:
                raw = read_frame(stdin)
            except OSError as exc:
                log.warning("frame error: %s", exc)
                return 1
            if raw is None:
                return 0
            try:
                msg = json.loads(raw)
                title = msg.get("title", "")
                href = msg.get("href", "")
                current_time_us = msg.get("currentTimeUs")
            except (ValueError, TypeError):
                write_frame(stdout, {"ok": False, "error": "bad json"})
                continue
            if not href:
                write_frame(stdout, {"ok": False, "error": "missing href"})
                continue
            ok, err = True, None
            try:
                r = client.post("/media/live", json={
                    "title": title,
                    "href": href,
                    "current_time_us": current_time_us,
                })
                ok = r.status_code < 400
                if not ok:
                    err = f"api {r.status_code}"
            except Exception as exc:  # noqa: BLE001
                ok, err = False, f"{type(exc).__name__}: {exc}"
                log.debug("media forward failed: %s", err)
            ack = {"ok": ok}
            if err:
                ack["error"] = err
            write_frame(stdout, ack)
    finally:
        client.close()


if __name__ == "__main__":
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        sys.exit(0)
