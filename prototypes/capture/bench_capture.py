"""Benchmark grim -> tesseract: latency and per-frame size across formats."""
import subprocess
import time
import statistics
import os
import json

OUT = os.path.dirname(os.path.abspath(__file__))
RESULT = os.path.join(OUT, "bench_results.json")


def run(cmd, timeout=60):
    t0 = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return time.monotonic() - t0, r


def grim_size(t, q, n=3):
    sizes = []
    for _ in range(n):
        t0 = time.monotonic()
        r = subprocess.run(["grim", "-t", t] + ([f"-q{q}"] if q else []) + ["-", ], capture_output=True)
        dt = time.monotonic() - t0
        sizes.append((len(r.stdout), dt))
    return sizes


def ocr(image_bytes, extra=()):
    p = subprocess.Popen(["tesseract", "stdin", "stdout"] + list(extra), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    t0 = time.monotonic()
    out, _ = p.communicate(image_bytes)
    return time.monotonic() - t0, out


def main():
    results = {}

    print("== grim per-frame size/latency (1920x1200) ==")
    formats = [("png", None), ("png", None), ("jpeg", 80), ("jpeg", 70), ("jpeg", 50), ("jpeg", 30)]
    for t, q in formats:
        sizes = grim_size(t, q)
        lbl = f"{t} q{q}" if q else (f"{t} l6" if t == "png" else t)
        avg = statistics.mean(s[0] for s in sizes)
        lat = statistics.mean(s[1] for s in sizes) * 1000
        results[lbl] = {"avg_bytes": avg, "grim_ms": lat}
        print(f"  {lbl:>12}: {avg/1024:7.1f}KiB  grim {lat:5.1f}ms")

    print("== tesseract latency & text (full res vs scaled) ==")
    full = subprocess.run(["grim", "-t", "jpeg", "-q", "80", "-"], capture_output=True).stdout
    for label, img in [("full jpeg80", full)]:
        dt, out = ocr(img)
        results[f"ocr_{label}"] = {"sec": dt, "chars": len(out)}
        print(f"  {label}: {dt:.2f}s  {len(out)} chars")
        print("    ", out[:100].decode(errors="replace").replace("\n", " | "))

    # scale knob: grim -s half and quarter
    for scale in ("0.5", "0.25"):
        img = subprocess.run(["grim", "-t", "jpeg", "-q", "80", "-s", scale, "-"],
                             capture_output=True).stdout
        dt, out = ocr(img)
        results[f"ocr_scale{scale}"] = {"sec": dt, "chars": len(out), "bytes": len(img)}
        print(f"  scale {scale}: {len(img)/1024:.0f}KiB  {dt:.2f}s  {len(out)} chars")
        print("    ", out[:100].decode(errors="replace").replace("\n", " | "))

    with open(RESULT, "w") as f:
        json.dump(results, f, indent=1)
    print("wrote", RESULT)


if __name__ == "__main__":
    main()
