"""Throwaway capture loop prototype for ticket #5.

Listens to Hyprland socket2, debounces + throttles capture, runs grim -> tesseract,
records every raw event and each stored frame into sqlite for analysis.

Usage:
  python3 capture_loop.py --log-only              # only log socket2 events (gap analysis)
  python3 capture_loop.py --run 30 --debounce 1.5 --min-interval 10 --keepalive 5 --dedupe
"""
import argparse
import json
import os
import queue
import socket
import sqlite3
import subprocess
import threading
import time

SOCK_DIR = "/run/user/1000/hypr"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capture.sqlite3")
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    ts REAL PRIMARY KEY,
    raw TEXT
);
CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    class TEXT, title TEXT, workspace TEXT, monitor TEXT, fullscreen INTEGER,
    size_bytes INTEGER, ocr_sec REAL, ocr_text TEXT,
    trigger TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    start REAL, end REAL, debounce REAL, min_interval REAL, keepalive REAL, dedupe INTEGER
);
"""

CAPTURE_EVENTS = ("activewindow>>", "activewindowv2>>", "openwindow>>", "fullscreen>>",
                  "workspace>>", "workspacev2>>")


def find_socket():
    for inst in os.listdir(SOCK_DIR):
        p = os.path.join(SOCK_DIR, inst, ".socket2.sock")
        if os.path.exists(p):
            return p
    raise FileNotFoundError("no Hyprland socket2 found")


def open_socket():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(find_socket())
    return s


def get_active():
    r = subprocess.run(["hyprctl", "activewindow", "-j"], capture_output=True)
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)


def grim_jpeg():
    r = subprocess.run(["grim", "-t", "jpeg", "-q", "80", "-"], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def ocr(img):
    p = subprocess.Popen(["tesseract", "stdin", "stdout"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    t0 = time.monotonic()
    out, _ = p.communicate(img)
    return time.monotonic() - t0, out.decode(errors="replace")


def listener(conn, stop, raw_q):
    """Read socket2, persist every event, forward capture-worthy ones."""
    buf = b""
    s = open_socket()
    while not stop.is_set():
        try:
            s.settimeout(5)
            data = s.recv(65536)
            if data:
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    raw = line.decode()
                    conn.execute("INSERT INTO events (ts, raw) VALUES (?, ?)",
                                 (time.time(), raw))
                    conn.commit()
                    if any(raw.startswith(p) for p in CAPTURE_EVENTS):
                        raw_q.put(raw)
            else:
                s.close()
                s = open_socket()
        except socket.timeout:
            pass
        except OSError:
            time.sleep(1)
            try:
                s.close()
                s = open_socket()
            except Exception:
                pass


def debouncer(stop, raw_q, jobs, debounce):
    """One fire per burst: collect capture events, fire after DEBOUNCE s of quiet."""
    pending = None
    while not stop.is_set():
        if pending is None:
            try:
                raw = raw_q.get(timeout=0.5)
            except queue.Empty:
                continue
            pending = (time.time() + debounce, time.time(), raw.split(">>")[0])
            continue
        deadline, ts, trig = pending
        wait = deadline - time.time()
        if wait <= 0:
            jobs.put((trig, ts))
            pending = None
            continue
        try:
            raw = raw_q.get(timeout=wait)
            pending = (time.time() + debounce, ts, raw.split(">>")[0])
        except queue.Empty:
            jobs.put((trig, ts))
            pending = None


def keepalive_loop(stop, jobs, interval_min):
    while not stop.is_set():
        stop.wait(interval_min * 60)
        if not stop.is_set():
            jobs.put(("keepalive", time.time()))


def worker(conn, jobs, stats, min_interval, dedupe):
    last_fire = 0.0
    last_meta = None
    while True:
        item = jobs.get()
        if item is None:
            break
        trigger, ts = item
        now = time.time()
        if now - last_fire < min_interval:
            stats["throttled"] += 1
            continue
        last_fire = now
        stats["fires"] += 1
        img = grim_jpeg()
        if img is None:
            stats["grim_fail"] += 1
            continue
        meta = get_active() or {}
        ws = meta.get("workspace", {})
        wname = f"{ws.get('id')}:{ws.get('name')}"
        sig = (meta.get("class"), meta.get("title"), wname)
        if dedupe and sig == last_meta:
            stats["dedup_skip"] += 1
            continue
        last_meta = sig
        osec, text = ocr(img)
        conn.execute(
            "INSERT INTO frames (ts, class, title, workspace, monitor, fullscreen,"
            " size_bytes, ocr_sec, ocr_text, trigger) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ts, meta.get("class"), meta.get("title"), wname, meta.get("monitor"),
             meta.get("fullscreen"), len(img), osec, text, trigger))
        conn.commit()
        stats["frames"] += 1
        stats["ocr_sec_total"] += osec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-only", action="store_true")
    ap.add_argument("--run", type=float, default=30, help="minutes to run")
    ap.add_argument("--db", default=DB)
    ap.add_argument("--debounce", type=float, default=1.5)
    ap.add_argument("--min-interval", type=float, default=10)
    ap.add_argument("--keepalive", type=float, default=0, help="minutes; 0=off")
    ap.add_argument("--dedupe", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect(a.db, check_same_thread=False)
    conn.executescript(SCHEMA)
    stats = {"fires": 0, "frames": 0, "throttled": 0, "grim_fail": 0,
             "dedup_skip": 0, "ocr_sec_total": 0.0}
    stop = threading.Event()
    raw_q, jobs = queue.Queue(), queue.Queue()

    threads = [
        threading.Thread(target=listener, args=(conn, stop, raw_q), daemon=True),
        threading.Thread(target=debouncer, args=(stop, raw_q, jobs, a.debounce), daemon=True),
        threading.Thread(target=worker, args=(conn, jobs, stats, a.min_interval, a.dedupe),
                         daemon=True),
    ]
    if a.keepalive > 0:
        threads.append(threading.Thread(target=keepalive_loop,
                                        args=(stop, jobs, a.keepalive), daemon=True))
    for t in threads:
        t.start()

    start = time.time()
    end = start + a.run * 60
    conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",
                 (start, end, a.debounce, a.min_interval, a.keepalive, int(a.dedupe)))
    conn.commit()
    print(f"capturing until {time.strftime('%H:%M:%S', time.localtime(end))} "
          f"({a.run:.0f} min); debounce={a.debounce}s min={a.min_interval}s "
          f"keepalive={a.keepalive}min dedupe={a.dedupe}")

    while time.time() < end and not stop.is_set():
        stop.wait(5)
    stop.set()
    time.sleep(1)
    jobs.put(None)
    conn.execute("UPDATE runs SET end=? WHERE start=?", (time.time(), start))
    conn.commit()
    print(json.dumps(stats, indent=1))
    n_ev = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    n_fr = conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
    print(f"db now has {n_ev} events, {n_fr} frames")
    conn.close()


if __name__ == "__main__":
    main()
