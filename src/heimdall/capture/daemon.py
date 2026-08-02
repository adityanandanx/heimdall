"""Event-driven capture daemon.

Threads: socket2 listener -> debouncer -> capture workers -> OCR workers, plus
a keepalive timer, an MPRIS follower and a heartbeat. grim/tesseract/hyprctl/
playerctl/socket2 all sit behind `CaptureTools` so the rest is plain wiring.

Not unit-tested (the pure decision logic lives in events.py / spans.py).
"""

from __future__ import annotations

import json
import logging
import os
import queue
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from heimdall.capture.events import activewindow_signature, classify_trigger, is_duplicate, is_track_change, parse_socket2_line, should_capture, workspace_id
from heimdall.config import Config, load_config
from heimdall.db import Database, init_db

log = logging.getLogger("heimdall.capture")

Trigger = str
Job = tuple[str, int]  # (trigger, ts_ms)


@dataclass
class CaptureTools:
    """Interface for the subprocess tools — injectable, never directly tested."""

    socket_dir: str = "/run/user/1000/hypr"
    grim: Callable[[int, int, int, int], Optional[bytes]] = field(default=None)
    activewindow: Callable[[], Optional[dict]] = field(default=None)
    ocr: Callable[[bytes], tuple[float, str]] = field(default=None)
    playerctl_follow: Callable[[], Iterable[str]] = field(default=None)

    def __post_init__(self):
        if self.grim is None:
            self.grim = self._grim_region
        if self.activewindow is None:
            self.activewindow = self._activewindow
        if self.ocr is None:
            self.ocr = self._ocr
        if self.playerctl_follow is None:
            self.playerctl_follow = self._playerctl_follow

    def find_socket(self) -> str:
        for inst in os.listdir(self.socket_dir):
            p = os.path.join(self.socket_dir, inst, ".socket2.sock")
            if os.path.exists(p):
                return p
        raise FileNotFoundError(f"no Hyprland socket2 under {self.socket_dir}")

    @staticmethod
    def _grim_region(x: int, y: int, w: int, h: int) -> Optional[bytes]:
        r = subprocess.run(
            ["grim", "-g", f"{x},{y} {w}x{h}", "-t", "jpeg", "-q", "80", "-"],
            capture_output=True,
        )
        return r.stdout if r.returncode == 0 else None

    @staticmethod
    def _activewindow() -> Optional[dict]:
        r = subprocess.run(["hyprctl", "activewindow", "-j"], capture_output=True)
        if r.returncode != 0:
            return None
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _ocr(img: bytes) -> tuple[float, str]:
        p = subprocess.Popen(
            ["tesseract", "stdin", "stdout"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        t0 = time.monotonic()
        out, _ = p.communicate(img)
        return time.monotonic() - t0, out.decode(errors="replace")

    @staticmethod
    def _playerctl_follow() -> Iterable[str]:
        cmd = ["playerctl", "metadata", "--follow", "--format",
               "{{status}}|{{artist}}|{{title}}|{{album}}|{{playerName}}"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            for raw in p.stdout or []:
                yield raw.strip()
        finally:
            p.wait()

    def socket_lines(self, should_stop: Callable[[], bool]) -> Iterable[str]:
        """Blocking generator of complete socket2 event lines.

        Reconnects on EOF/error with a short sleep; checks `should_stop` between
        recvs so the listener thread can be torn down promptly. All socket IO
        lives here, behind the seam.
        """
        buf = b""
        while not should_stop():
            sock = None
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(self.find_socket())
                sock.settimeout(1)
                while not should_stop():
                    try:
                        data = sock.recv(65536)
                    except socket.timeout:
                        continue
                    if not data:
                        break  # server closed the socket -> reconnect
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        yield line.decode()
            except OSError:
                time.sleep(1)
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass


class CaptureDaemon:
    """Owns the queues, threads and DB writes. `run()` blocks until stopped."""

    def __init__(self, config: Config, tools: CaptureTools | None = None, db_path=None):
        self.config = config
        self.tools = tools or CaptureTools()
        data = config.data_path
        self.db_path = Path(db_path) if db_path else data / "data.db"
        self.db = Database(self.db_path)
        self.heartbeat = data / "capture.heartbeat"
        self.data = data
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._last_fire = 0.0
        self._last_sig: tuple | None = None
        self._last_track: tuple | None = None
        self._last_track_status: str | None = None
        self.events_q: queue.Queue[str] = queue.Queue()
        self.jobs: queue.Queue[Job] = queue.Queue()
        self.ocr_jobs: queue.Queue[tuple[int, bytes]] = queue.Queue()
        self._threads: list[threading.Thread] = []

    # ---- threads ----

    def _listener(self) -> None:
        for line in self.tools.socket_lines(self._stop.is_set):
            self._on_event(line)

    def _on_event(self, line: str) -> None:
        parsed = parse_socket2_line(line)
        if not parsed:
            return
        now_ms = int(time.time() * 1000)
        self.db.insert_event(ts=now_ms, raw=line)
        trigger = classify_trigger(parsed["type"])
        if trigger:
            self.events_q.put(f"{trigger}:{now_ms}")

    def _debouncer(self) -> None:
        pending: tuple[float, str, float] | None = None
        while not self._stop.is_set():
            if pending is None:
                try:
                    item = self.events_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                trigger, ts = item.split(":", 1)
                pending = (time.time() + self.config.capture.debounce_s, trigger, time.time())
                continue
            deadline, trigger, start = pending
            wait = deadline - time.time()
            if wait <= 0:
                self.jobs.put((trigger, int(start * 1000)))
                pending = None
                continue
            try:
                item = self.events_q.get(timeout=wait)
            except queue.Empty:
                self.jobs.put((trigger, int(start * 1000)))
                pending = None
                continue
            new_trigger, _ = item.split(":", 1)
            pending = (time.time() + self.config.capture.debounce_s, new_trigger, start)

    def _keepalive(self) -> None:
        interval = self.config.capture.keepalive_min * 60
        while not self._stop.wait(interval):
            self.jobs.put(("keepalive", int(time.time() * 1000)))

    def _mpris(self) -> None:
        while not self._stop.is_set():
            try:
                for line in self.tools.playerctl_follow():
                    if line and not self._stop.is_set():
                        self._on_track(line)
            except FileNotFoundError:
                log.warning("playerctl not found; MPRIS capture disabled")
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("mpris loop error: %s", exc)
            self._stop.wait(5)

    def _on_track(self, line: str) -> None:
        parts = line.split("|")
        status = parts[0] if parts else ""
        artist = parts[1] if len(parts) > 1 else ""
        title = parts[2] if len(parts) > 2 else ""
        album = parts[3] if len(parts) > 3 else ""
        player = parts[4] if len(parts) > 4 else "unknown"
        now_ms = int(time.time() * 1000)
        self.db.insert_track(ts=now_ms, player=player, artist=artist or None,
                             title=title, album=album or None, status=status or None)
        # capture on playback start/resume and on mid-play track switches (#5);
        # paused states never capture — a paused first sighting or a track
        # switch while paused is not listening time
        changed = is_track_change(self._last_track, player, artist, title)
        resumed = status == "playing" and self._last_track_status != "playing"
        if changed:
            self._last_track = (player, artist or "", title or "")
        self._last_track_status = status
        if status == "playing" and (changed or resumed):
            self.jobs.put(("mpris", now_ms))

    def _capture_worker(self) -> None:
        while True:
            item = self.jobs.get()
            if item is None:
                break
            trigger, ts = item
            now = time.monotonic()
            with self._lock:
                if not should_capture(now, self._last_fire, self.config.capture.min_interval_s):
                    continue
                self._last_fire = now
            meta = self.tools.activewindow()
            if not meta:
                continue
            sig = activewindow_signature(meta)
            with self._lock:
                if is_duplicate(sig, self._last_sig):
                    continue
                self._last_sig = sig
            at, size = meta.get("at") or [], meta.get("size") or []
            if len(at) < 2 or len(size) < 2:
                continue
            img = self.tools.grim(int(at[0]), int(at[1]), int(size[0]), int(size[1]))
            if not img:
                log.warning("grim capture failed")
                continue
            frame_id = self._store_frame(ts, meta, trigger, img)
            if frame_id:
                self.ocr_jobs.put((frame_id, img))

    def _store_frame(self, ts: int, meta: dict, trigger: str, img: bytes) -> Optional[int]:
        dt = time.localtime(ts / 1000)
        rel_dir = f"frames/{dt.tm_year:04d}/{dt.tm_mon:02d}/{dt.tm_mday:02d}"
        day_dir = self.data / rel_dir
        day_dir.mkdir(parents=True, exist_ok=True)
        image_path = f"{rel_dir}/{ts}.jpg"
        (day_dir / f"{ts}.jpg").write_bytes(img)
        return self.db.insert_frame({
            "ts": ts,
            "monitor": meta.get("monitor"),
            "workspace": workspace_id(meta),
            "window_class": meta.get("class") or "",
            "window_title": meta.get("title"),
            "fullscreen": int(meta.get("fullscreen") or 0),
            "trigger": trigger,
            "image_path": image_path,
            "image_bytes": len(img),
            "ocr_text": None,
            "ocr_sec": None,
        })

    def _ocr_worker(self) -> None:
        while True:
            item = self.ocr_jobs.get()
            if item is None:
                break
            frame_id, img = item
            secs, text = self.tools.ocr(img)
            with self.db.conn() as conn:
                conn.execute("UPDATE frames SET ocr_text = ?, ocr_sec = ? WHERE id = ?",
                             (text, secs, frame_id))
                conn.commit()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(15):
            self._write_heartbeat()

    def _write_heartbeat(self) -> None:
        try:
            self.heartbeat.parent.mkdir(parents=True, exist_ok=True)
            self.heartbeat.write_text(str(int(time.time() * 1000)))
        except OSError:
            pass

    # ---- lifecycle ----

    def start(self) -> None:
        init_db(self.db_path)
        self._write_heartbeat()
        threads = [
            threading.Thread(target=self._listener, name="socket2", daemon=True),
            threading.Thread(target=self._debouncer, name="debouncer", daemon=True),
            threading.Thread(target=self._keepalive, name="keepalive", daemon=True),
            threading.Thread(target=self._mpris, name="mpris", daemon=True),
            threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True),
        ]
        threads += [
            threading.Thread(target=self._capture_worker, name=f"capture-{i}", daemon=True)
            for i in range(max(1, self.config.capture.ocr_workers))
        ]
        threads += [
            threading.Thread(target=self._ocr_worker, name=f"ocr-{i}", daemon=True)
            for i in range(max(1, self.config.capture.ocr_workers))
        ]
        self._threads = threads
        for t in threads:
            t.start()
        log.info("capture daemon started (keepalive=%smin, min_interval=%ss)",
                 self.config.capture.keepalive_min, self.config.capture.min_interval_s)

    def stop(self) -> None:
        self._stop.set()
        self.jobs.put(None)
        for _ in self._threads:
            self.ocr_jobs.put(None)
        for t in self._threads:
            t.join(timeout=3)

    def run(self) -> None:
        self.start()
        try:
            while not self._stop.is_set():
                self._stop.wait(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


def main() -> None:
    """`python -m heimdall.capture.daemon [--config PATH]` — used by scripts/start-capture.sh."""
    import argparse

    parser = argparse.ArgumentParser(prog="heimdall-capture", description="event-driven capture daemon")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("--log-dir", default=None, help="write log to <dir>/capture.log instead of stderr")
    args = parser.parse_args()

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_dir:
        log_dir = Path(args.log_dir).expanduser()
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "capture.log"))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    CaptureDaemon(load_config(args.config)).run()


if __name__ == "__main__":
    main()
