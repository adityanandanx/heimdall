"""Analyze capture.sqlite3: event burstiness, silent gaps, capture cadence, storage."""
import argparse
import sqlite3
import statistics

DEFAULTS = {
    "frame_kib": 284,     # measured JPEG q80, 1920x1200
    "ocr_sec": 4.3,
}


def main(db, frame_kib, ocr_sec):
    c = sqlite3.connect(db)
    n = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    if not n:
        print("no events yet"); return
    rows = c.execute("SELECT ts, raw FROM events ORDER BY ts").fetchall()
    ts = [r[0] for r in rows]
    span = ts[-1] - ts[0]
    hrs = span / 3600

    print(f"== events: {n} over {span/60:.1f} min ({hrs:.2f}h) ==")

    # per-event-type counts
    types = {}
    for _, raw in rows:
        t = raw.split(">>")[0]
        types[t] = types.get(t, 0) + 1
    print("types:", dict(sorted(types.items(), key=lambda kv: -kv[1])))

    # inter-event gaps
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    gaps_sorted = sorted(gaps)
    print(f"inter-event gap: med {statistics.median(gaps):.1f}s  p90 {gaps_sorted[int(len(gaps)*0.9)]:.1f}s "
          f"max {max(gaps):.0f}s ({max(gaps)/60:.1f} min)")

    # silent gaps: runs where no events for >= 30s
    silent = [g for g in gaps if g >= 30]
    tot_silent = sum(silent)
    print(f"gaps >=30s: {len(silent)} (tot {tot_silent/60:.1f} min = {tot_silent/span*100:.0f}% of span)")
    for s in sorted(silent, reverse=True)[:8]:
        print(f"    {s/60:6.1f} min")

    # window dwell: spans where activewindow/class,title stays constant
    dwell = {}
    last_class, last_title, start = None, None, ts[0]
    for rts, raw in rows:
        if raw.startswith("activewindow>>"):
            cls, _, title = raw.partition(">>")[2].partition(",")
            if (cls, title) != (last_class, last_title):
                if last_title:
                    d = rts - start
                    dwell[(last_class, last_title[:40])] = dwell.get((last_class, last_title[:40]), 0) + d
                last_class, last_title = cls, title
                start = rts
    print("== top window dwell (event-driven visibility) ==")
    for (cls, title), d in sorted(dwell.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {cls[:12]:12} {d/60:7.1f} min  {title}")

    # capture cadence under pure event-driven with debounce+min_interval
    print("== pure event-driven capture (debounce 1.5s) ==")
    active_hours = 12.0
    fires_hr = {}
    for min_int in (10, 30, 60):
        fires, last = 0, 0
        for g in gaps:
            if g >= 1.5 and g >= min_int:  # approx: fire if gap>debounce and >min_interval
                fires += 1
        fires_hr[min_int] = fires / hrs if hrs > 0 else 0
        day_frames = fires_hr[min_int] * active_hours
        print(f"    min_interval {min_int:>3}s -> ~{fires_hr[min_int]:5.1f} fires/h -> "
              f"{day_frames:5.0f} frames/12h-day -> {day_frames*frame_kib/1024/1024*30:4.1f} GiB/month")

    # keepalive storage
    print("== keepalive storage (12h active day) ==")
    for ka in (2, 5, 10, 15, 30):
        fpd = 12 * 60 / ka
        print(f"    every {ka:>2} min -> {fpd:5.0f} frames/day -> {fpd*frame_kib/1024/1024*30:5.1f} GiB/month")

    print(f"(frame 284KiB JPEG q80, OCR {ocr_sec}s/frame -> sustained cap "
          f"{1/ocr_sec*3600:.0f} frames/h)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/home/aditya/stuff/heimdall/prototypes/capture/capture.sqlite3")
    ap.add_argument("--frame-kib", type=float, default=DEFAULTS["frame_kib"])
    ap.add_argument("--ocr-sec", type=float, default=DEFAULTS["ocr_sec"])
    a = ap.parse_args()
    main(a.db, a.frame_kib, a.ocr_sec)
