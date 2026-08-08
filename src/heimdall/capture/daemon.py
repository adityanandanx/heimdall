"""Event-driven capture daemon.

Threads: socket2 listener -> debouncer -> capture workers -> extraction
workers, plus a keepalive timer, an MPRIS follower, a watch-session poll loop
and a heartbeat. grim/hyprctl/playerctl/socket2 and the AT-SPI reader all sit
behind `CaptureTools` so the rest is plain wiring.

Not unit-tested (the pure decision logic lives in events.py / spans.py /
a11y.py / sessions.py).
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

from heimdall.capture.a11y import content_bearing, flatten_text
from heimdall.capture.events import activewindow_signature, classify_trigger, is_duplicate, is_track_change, parse_socket2_line, should_capture, workspace_id
from heimdall.capture.ocr import route_extraction
from heimdall.capture.phash import phash
from heimdall.capture.sessions import SessionTracker, WatchSession, normalize_player, parse_mpris_line
from heimdall.config import DEFAULT_CONFIG_PATH, Config, load_config
from heimdall.db import Database, init_db

log = logging.getLogger("heimdall.capture")

Trigger = str
Job = tuple[str, int]  # (trigger, ts_ms)
ExtractJob = tuple[int, str, str, bytes]  # (frame_id, window_class, window_title, image)

# Manual-capture requests (POST /capture -> capture.request) older than this are
# stale and ignored on daemon startup, so a leftover file never fires a capture.
MANUAL_REQUEST_MAX_AGE_MS = 30_000


@dataclass
class CaptureTools:
    """Interface for the subprocess tools — injectable, never directly tested."""

    socket_dir: str = "/run/user/1000/hypr"
    grim: Callable[[int, int, int, int], Optional[bytes]] = field(default=None)
    activewindow: Callable[[], Optional[dict]] = field(default=None)
    a11y_read: Callable[[str, str], Optional[list]] = field(default=None)
    rapid_ocr: Callable[[bytes], Optional[str]] = field(default=None)
    playerctl_follow: Callable[[], Iterable[str]] = field(default=None)
    list_players: Callable[[], list[str]] = field(default=None)
    playerctl_position: Callable[[str], Optional[int]] = field(default=None)
    cdp_resolve: Callable[[str, Optional[int]], Optional[dict]] = field(default=None)
    media_resolver: str = "extension"  # extension|cdp: Chromium URL source of truth (#44)
    transcript_fetch: Callable[[str, list], Optional[dict]] = field(default=None)
    captions_dir: Path = field(default=None, repr=False)
    db: object = field(default=None, repr=False)
    ocr_engine: str = "auto"  # live-read at call time; daemon reload updates it (#70)
    _cdp_session: object = field(default=None, init=False, repr=False)
    _ext_resolver: object = field(default=None, init=False, repr=False)
    _caption_cache: object = field(default=None, init=False, repr=False)

    def __post_init__(self):
        if self.grim is None:
            self.grim = self._grim_region
        if self.activewindow is None:
            self.activewindow = self._activewindow
        if self.a11y_read is None:
            self.a11y_read = self._a11y_read
        if self.rapid_ocr is None:
            self.rapid_ocr = self._rapid_ocr(self)
        if self.playerctl_follow is None:
            self.playerctl_follow = self._playerctl_follow
        if self.list_players is None:
            self.list_players = self._list_players
        if self.playerctl_position is None:
            self.playerctl_position = self._playerctl_position
        if self.cdp_resolve is None:
            if self.media_resolver == "cdp":
                self.cdp_resolve = self._cdp_resolve
            else:
                self.cdp_resolve = self._extension_resolve
        if self.transcript_fetch is None:
            self.transcript_fetch = self._transcript_fetch

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
    def _a11y_read(window_class: str, window_title: str) -> Optional[list]:
        """AT-SPI tree for the window (class+title); None when off-bus."""
        from heimdall.capture import a11y

        return a11y.read_window_tree(window_class, window_title)

    @staticmethod
    def _rapid_ocr(tools: "CaptureTools") -> Callable[[bytes], Optional[str]]:
        def run(img: bytes) -> Optional[str]:
            from heimdall.capture import ocr

            return ocr.rapid_ocr(img, engine=tools.ocr_engine)

        return run

    @staticmethod
    def _playerctl_follow() -> Iterable[str]:
        cmd = ["playerctl", "metadata", "--follow", "--format",
               "{{status}}|{{artist}}|{{title}}|{{album}}|{{playerName}}"
               "|{{position}}|{{mpris:length}}|{{xesam:url}}"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            for raw in p.stdout or []:
                yield raw.strip()
        finally:
            p.wait()

    @staticmethod
    def _list_players() -> list[str]:
        r = subprocess.run(["playerctl", "-l"], capture_output=True, text=True)
        if r.returncode != 0:
            return []
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]

    @staticmethod
    def _playerctl_position(player: str) -> Optional[int]:
        """Position in video-time microseconds, or None when the player is gone."""
        r = subprocess.run(
            ["playerctl", "metadata", "-p", player, "--format", "{{position}}"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return None
        try:
            return int(r.stdout.strip())
        except ValueError:
            return None

    def _cdp_resolve(self, window_title: str, position_us: Optional[int]) -> Optional[dict]:
        """Resolve {media_source, media_id} for a Chromium page via CDP (#36).

        Reuses one long-lived CDP connection so Chrome's per-connection
        "Allow remote debugging?" prompt appears once per browser start, not
        once per poll tick.
        """
        if self._cdp_session is None:
            from heimdall.capture import cdp

            self._cdp_session = cdp.CdpSession()
        return self._cdp_session.resolve_chromium_media(
            window_title=window_title, position_us=position_us,
        )

    def _extension_resolve(self, window_title: str,
                           position_us: Optional[int]) -> Optional[dict]:
        """Resolve {media_source, media_id} from the extension stream (#44).

        Reads the native-messaging stream (``media_stream`` table) and
        title-matches the open session; an empty stream or missing db degrades
        to title-only with no crash.
        """
        if self._ext_resolver is None:
            if self.db is None:
                return None
            from heimdall.capture.extension import ExtensionResolver

            self._ext_resolver = ExtensionResolver(self.db)
        return self._ext_resolver.resolve(window_title, position_us)

    def _transcript_fetch(self, media_id: str, ranges: list) -> Optional[dict]:
        """Sliced captions for one closed session: {cues_json, transcript}.

        Shared seam with the API's manual transcript re-fetch (#65) — see
        ``captions.fetch_sliced_captions``. Any failure returns None so the
        session stays title-only.
        """
        from heimdall.capture.captions import fetch_sliced_captions

        return fetch_sliced_captions(media_id, ranges, self.captions_dir)

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


def _player_present(player: str, players: set[str]) -> bool:
    """True when `player` (the `{{playerName}}` base, e.g. ``chromium``) is
    among the `playerctl -l` instances (e.g. ``chromium.instance1220``).

    `{{playerName}}` strips the instance suffix while `playerctl -l` returns
    the full instance name, so a base name matches exactly or as a prefix.
    """
    return any(p == player or p.startswith(player + ".") for p in players)


class CaptureDaemon:
    """Owns the queues, threads and DB writes. `run()` blocks until stopped."""

    def __init__(self, config: Config, tools: CaptureTools | None = None, db_path=None,
                 config_path: str | None = None):
        self.config = config
        self.config_path = config_path
        data = config.data_path
        self.db_path = Path(db_path) if db_path else data / "data.db"
        self.db = Database(self.db_path)
        if tools is None:
            tools = CaptureTools(
                media_resolver=config.watch.media_resolver,
                captions_dir=config.captions_path,
                db=self.db,
                ocr_engine=config.capture.ocr_engine,
            )
        self.tools = tools
        self.tools.ocr_engine = config.capture.ocr_engine
        self.heartbeat = data / "capture.heartbeat"
        self.engine_file = data / "capture.engine"
        self.manual_request = data / "capture.request"
        self.manual_ack = data / "capture.ack"
        self.data = data
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._last_fire = 0.0
        self._last_sig: tuple | None = None
        self._last_track: tuple | None = None
        self._last_track_status: str | None = None
        self._manual_rid: str | None = None
        self._manual_pending = False
        self.tracker = SessionTracker(pause_ends_session_s=config.watch.pause_ends_session_s)
        self._excluded_players = set(config.watch.excluded_players)
        self._excluded_windows = set(config.watch.excluded_windows)
        self._live_rows: dict[str, int] = {}  # player -> watch_sessions row id
        self._last_phash: dict[str, str] = {}  # window_class -> phash (change gate, #34)
        self.events_q: queue.Queue[str] = queue.Queue()
        self.jobs: queue.Queue[Job] = queue.Queue()
        self.extract_jobs: queue.Queue[ExtractJob] = queue.Queue()
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

    def _manual_loop(self) -> None:
        """Poll the manual-capture request file (`heimdall capture` -> /capture)."""
        while not self._stop.wait(0.5):
            self._check_manual()

    def _check_manual(self) -> None:
        """Enqueue a `manual` capture when a fresh, new request file appears.

        Only one manual capture runs at a time (`_manual_pending`); the capture
        worker acks it back to `capture.ack` so the API call can return.
        """
        if self._manual_pending:
            return
        try:
            payload = json.loads(self.manual_request.read_text())
        except (FileNotFoundError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        rid = payload.get("id")
        ts = payload.get("ts")
        if not rid or not isinstance(ts, int):
            return
        if rid == self._manual_rid or int(time.time() * 1000) - ts > MANUAL_REQUEST_MAX_AGE_MS:
            return
        self._manual_rid = rid
        self._manual_pending = True
        self.jobs.put(("manual", int(time.time() * 1000)))

    def _manual_ack(self, *, status: str, frame_id: int | None = None,
                    detail: str | None = None) -> None:
        """Reply to a manual-capture request (best-effort; capture never fails).

        The request id is kept after acking so the same `capture.request` file
        is not treated as a fresh request on the next poll — the file is never
        deleted, so resetting the id here would re-fire a capture every 0.5s
        until a *different* request id overwrites it.
        """
        if self._manual_rid is None:
            return
        try:
            self.manual_ack.write_text(json.dumps({
                "id": self._manual_rid,
                "status": status,
                "frame_id": frame_id,
                "detail": detail,
            }))
        except OSError:
            pass
        self._manual_pending = False

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
        self._update_watch_session(line, now_ms)

    def _update_watch_session(self, line: str, now_ms: int) -> None:
        """Drive the watch-session tracker from the follow line (#35).

        playing opens (or resumes) a session — the tracker closes the old one
        itself when the track changes; paused marks a streak boundary; stopped
        closes. A stopped line carries position 0, so the session is ended at
        the last known position (like a player exit).
        """
        parsed = parse_mpris_line(line)
        if parsed is None:
            return
        player = parsed["player"]
        if normalize_player(player) in self._excluded_players:
            return
        if parsed["status"] == "playing":
            closed = self.tracker.play(
                player,
                title=parsed["title"],
                source=parsed["source"],
                position_us=parsed["position_us"],
                length_us=parsed["length_us"],
                wall_ms=now_ms,
            )
            self._persist_session(closed)
        elif parsed["status"] == "paused":
            self.tracker.pause(player, parsed["position_us"], now_ms)
        else:
            closed = self.tracker.stop(player, parsed["position_us"], now_ms) if parsed["position_us"] > 0 else self.tracker.exit(player, now_ms)
            self._persist_session(closed)
        self._sync_live_rows(now_ms)

    def _sync_live_rows(self, now_ms: int) -> None:
        """Keep watch_sessions live rows in sync with the tracker snapshot.

        Runs after every follow line and poll tick: opens a row the first time
        a player is seen, updates it on every later sighting, and forgets
        players whose session closed (the close path already finalized them).
        """
        snaps = self.tracker.snapshot()
        seen: set[str] = set()
        for s in snaps:
            seen.add(s.player)
            row_id = self._live_rows.get(s.player)
            if row_id is None:
                self._live_rows[s.player] = self.db.insert_live_session(
                    s.player, s.media_title, s.media_source, s.media_id,
                    ts_start=s.ts_start, pos_start=s.pos_start,
                    length=s.length, ranges=s.ranges,
                )
            else:
                self.db.update_live_session(
                    row_id, ts_end=now_ms, pos_end=s.last_pos_us, ranges=s.ranges,
                )
        for player in [p for p in self._live_rows if p not in seen]:
            del self._live_rows[player]

    def _watch_poll(self) -> None:
        """Poll open players every watch.poll_interval_s: refresh position (seek
        detection + range end) and close sessions whose player disappeared."""
        while not self._stop.wait(self.config.watch.poll_interval_s):
            self._watch_poll_once()

    def _watch_poll_once(self) -> None:
        if self.config.capture.paused:
            now_ms = int(time.time() * 1000)
            for player in list(self.tracker.open_sessions()):
                self._persist_session(self.tracker.exit(player, now_ms))
            return
        try:
            players = set(self.tools.list_players())
        except Exception:  # noqa: BLE001
            players = None
        now_ms = int(time.time() * 1000)
        for player in list(self.tracker.open_sessions()):
            if players is not None and not _player_present(player, players):
                self._persist_session(self.tracker.exit(player, now_ms))
                continue
            position_us = self.tools.playerctl_position(player)
            if position_us is None:
                continue
            self._persist_session(self.tracker.poll(player, position_us, now_ms))
        self._enrich_chromium_media()
        self._sync_live_rows(now_ms)

    def _enrich_chromium_media(self) -> None:
        """CDP-resolve missing media for open Chromium sessions (#36).

        Runs on each poll tick: reads the exact URL + video id from the DevTools
        endpoint and writes them into the tracker and live row. Fail-soft — any
        CDP failure leaves the session title-only.
        """
        resolve = getattr(self.tools, "cdp_resolve", None)
        if resolve is None:
            return
        for snap in self.tracker.snapshot():
            if normalize_player(snap.player) != "chromium" or snap.media_source:
                continue
            try:
                resolved = resolve(snap.media_title or "", snap.last_pos_us)
            except Exception:  # noqa: BLE001
                log.warning("cdp resolution failed for %s", snap.player)
                continue
            if not resolved or not resolved.get("media_source"):
                continue
            self.tracker.set_media(
                snap.player, resolved["media_source"], resolved.get("media_id"),
            )
            row_id = self._live_rows.get(snap.player)
            if row_id is not None:
                self.db.update_live_media(
                    row_id,
                    media_source=resolved["media_source"],
                    media_id=resolved.get("media_id"),
                )

    def _persist_session(self, closed: Optional[WatchSession]) -> None:
        if closed is None:
            return
        row_id = self._live_rows.pop(closed.player, None)
        if row_id is not None:
            self.db.finalize_live_session(
                row_id,
                ts_end=closed.ts_end,
                pos_end=closed.pos_end,
                ranges=closed.ranges,
            )
        else:
            row_id = self.db.insert_watch_session(closed)
        self._attach_transcript(closed, row_id)

    def _attach_transcript(self, closed: WatchSession, row_id: int) -> None:
        """Attach sliced captions to a closed chromium session (#38).

        Fires only when the session has a resolvable YouTube media_id; every
        failure path returns None from `transcript_fetch` so the row stays
        title-only. Wrapped in try/except as the daemon's final say.
        """
        resolve = getattr(self.tools, "transcript_fetch", None)
        if resolve is None or not closed.media_id:
            return
        if normalize_player(closed.player) != "chromium":
            return
        try:
            result = resolve(closed.media_id, closed.ranges)
        except Exception:  # noqa: BLE001 — capture must never fail a session
            log.warning("transcript attach failed for %s", closed.media_id)
            return
        if not result:
            return
        try:
            self.db.update_session_transcript(
                row_id,
                cues_json=result["cues_json"],
                transcript=result["transcript"],
                transcript_source="captions",
            )
        except Exception:  # noqa: BLE001
            log.warning("transcript persist failed for %s", closed.media_id)

    def _capture_worker(self) -> None:
        while True:
            item = self.jobs.get()
            if item is None:
                break
            trigger, ts = item
            manual = trigger == "manual"
            if self.config.capture.paused:
                if manual:
                    self._manual_ack(status="error", detail="capture is paused (#76)")
                continue
            now = time.monotonic()
            with self._lock:
                # a manual capture always fires regardless of the interval gate
                if not manual and not should_capture(now, self._last_fire, self.config.capture.min_interval_s):
                    continue
                self._last_fire = now
            meta = self.tools.activewindow()
            if not meta:
                self._manual_ack(status="error", detail="no active window found")
                continue
            if not manual and (meta.get("class") or "") in self._excluded_windows:
                continue
            sig = activewindow_signature(meta)
            with self._lock:
                if not manual and is_duplicate(sig, self._last_sig):
                    continue
                self._last_sig = sig
            at, size = meta.get("at") or [], meta.get("size") or []
            if len(at) < 2 or len(size) < 2:
                self._manual_ack(status="error", detail="active window has no geometry")
                continue
            img = self.tools.grim(int(at[0]), int(at[1]), int(size[0]), int(size[1]))
            if not img:
                log.warning("grim capture failed")
                self._manual_ack(status="error", detail="grim capture failed")
                continue
            frame_id = self._store_frame(ts, meta, trigger, img)
            if frame_id is None:
                self._manual_ack(status="error", detail="frame not stored")
                continue
            if manual:
                self._manual_ack(status="ok", frame_id=frame_id)
            if self._should_extract(trigger, meta.get("class") or "", img):
                self.extract_jobs.put(
                    (frame_id, meta.get("class") or "", meta.get("title") or "", img)
                )

    def _should_extract(self, trigger: str, window_class: str, img: bytes) -> bool:
        """Per-window change gate (#34): a keepalive capture whose pixels are
        unchanged for the window is stored but not re-extracted; event-triggered
        captures always extract. Disabled by capture.change_gate=false."""
        if not self.config.capture.change_gate:
            return True
        h = phash(img)
        if h is None:
            return True
        if trigger == "keepalive" and h == self._last_phash.get(window_class):
            return False
        self._last_phash[window_class] = h
        return True

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
            "source_url": self._frame_source_url(meta.get("title"), ts),
            "image_path": image_path,
            "image_bytes": len(img),
            "ocr_text": None,
            "ocr_sec": None,
        })

    def _frame_source_url(self, window_title: Optional[str], ts: int) -> Optional[str]:
        """Tab URL for a browser frame — the extension stream, title-matched
        like sessions (#64). Wrapped so a dead DB or absent stream never
        fails the capture."""
        try:
            return self.db.url_for_window(window_title or "", ts)
        except Exception:  # noqa: BLE001
            return None

    def _extract_worker(self) -> None:
        """Extraction queue: route each frame to a11y and/or RapidOCR (#34).

        `route_extraction` picks the source(s): a11y wins in auto mode, blind
        windows fall back to RapidOCR, and `window_class_merge` classes store
        both. RapidOCR runs in this queue so it never blocks a capture.
        """
        if self.config.capture.extraction not in ("auto", "a11y", "ocr"):
            log.warning("capture.extraction=%r is not a known mode; treating as auto",
                        self.config.capture.extraction)
        mode = self.config.capture.extraction
        merge = self.config.capture.window_class_merge
        while True:
            item = self.extract_jobs.get()
            if item is None:
                break
            frame_id, window_class, window_title, img = item
            tree = None
            if mode in ("auto", "a11y"):
                tree = self.tools.a11y_read(window_class, window_title)
            bearing = bool(tree and content_bearing(tree))
            route = route_extraction(mode, bearing, window_class, merge)
            if route in ("a11y", "both"):
                if bearing:
                    self.db.set_frame_extraction(
                        frame_id,
                        a11y_text=flatten_text(tree),
                        a11y_json=json.dumps(tree, ensure_ascii=False),
                    )
                else:
                    self.db.set_frame_extraction(frame_id, a11y_text=None, a11y_json=None)
            if route in ("ocr", "both"):
                text = self.tools.rapid_ocr(img)
                self.db.set_frame_extraction(
                    frame_id,
                    ocr_text=text,
                    ocr_engine="rapid",
                )

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(15):
            self._write_heartbeat()
            self._reload_config_if_dirty()

    def _reload_config_if_dirty(self) -> None:
        """Re-read config.yaml when the app wrote it (settings.dirty marker).

        Live settings (#70): the API server writes config.yaml then touches
        settings.dirty; this poll (15s cadence) picks it up and swaps
        self.config — extraction mode, OCR engine, exclusions, pause, cron.
        Non-config runtime state (session tracker, queues) is untouched.
        """
        try:
            dirty = self.data / "settings.dirty"
            marker_mtime = dirty.stat().st_mtime
        except OSError:
            return
        if getattr(self, "_config_mtime", 0.0) >= marker_mtime:
            return
        from heimdall.config import load_config

        try:
            self.config = load_config(self.config_path)
        except Exception as exc:  # noqa: BLE001 — never kill the loop on a bad file
            log.warning("config reload failed (keeping previous): %s", exc)
            return
        self._config_mtime = marker_mtime
        self._excluded_players = set(self.config.watch.excluded_players)
        self._excluded_windows = set(self.config.watch.excluded_windows)
        self.tools.ocr_engine = self.config.capture.ocr_engine
        self.tools.media_resolver = self.config.watch.media_resolver
        self._publish_engine()
        log.info("config reloaded (dirty marker); ocr_engine=%s paused=%s",
                 self.config.capture.ocr_engine, self.config.capture.paused)

    def _write_heartbeat(self) -> None:
        try:
            self.heartbeat.parent.mkdir(parents=True, exist_ok=True)
            self.heartbeat.write_text(str(int(time.time() * 1000)))
        except OSError:
            pass

    def _publish_engine(self) -> None:
        """Write the resolved OCR engine (npu|cpu) to a state file so the API
        server's /status can show configured vs active (#71). JSON: the server
        reads `active` only; `configured` is redundant with config but kept for
        a single-source readout."""
        try:
            from heimdall.capture import ocr

            active = ocr.active_engine() or (
                "npu" if self.config.capture.ocr_engine in ("npu", "auto") and self._npu_available() else "cpu"
            )
            self.engine_file.parent.mkdir(parents=True, exist_ok=True)
            self.engine_file.write_text(active)
        except OSError:
            pass

    @staticmethod
    def _npu_available() -> bool:
        try:
            from heimdall.capture.npu_ocr import install_npu_engine

            return install_npu_engine()
        except Exception:  # noqa: BLE001
            return False

    # ---- lifecycle ----

    def start(self) -> None:
        init_db(self.db_path)
        self._write_heartbeat()
        self._publish_engine()
        threads = [
            threading.Thread(target=self._listener, name="socket2", daemon=True),
            threading.Thread(target=self._debouncer, name="debouncer", daemon=True),
            threading.Thread(target=self._keepalive, name="keepalive", daemon=True),
            threading.Thread(target=self._mpris, name="mpris", daemon=True),
            threading.Thread(target=self._watch_poll, name="watch-poll", daemon=True),
            threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True),
            threading.Thread(target=self._manual_loop, name="manual", daemon=True),
        ]
        threads += [
            threading.Thread(target=self._capture_worker, name=f"capture-{i}", daemon=True)
            for i in range(max(1, self.config.capture.extract_workers))
        ]
        threads += [
            threading.Thread(target=self._extract_worker, name=f"extract-{i}", daemon=True)
            for i in range(max(1, self.config.capture.extract_workers))
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
            self.extract_jobs.put(None)
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
    parser.add_argument("--config", default=None, help="path to config.yaml (default ~/.heimdall/config.yaml)")
    parser.add_argument("--log-dir", default=None, help="write log to <dir>/capture.log instead of stderr")
    args = parser.parse_args()

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_dir:
        log_dir = Path(args.log_dir).expanduser()
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "capture.log"))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    # No --config flag: resolve the default so the dirty-marker reload and
    # settings writes always re-read the same file the server edits.
    CaptureDaemon(
        load_config(args.config),
        config_path=args.config or DEFAULT_CONFIG_PATH,
    ).run()


if __name__ == "__main__":
    main()
