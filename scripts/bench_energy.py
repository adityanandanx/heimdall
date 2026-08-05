#!/usr/bin/env python3
"""Thermal + energy bench: how hot and how battery-hungry is each OCR engine?

Modes (all sustained over the same corpus, cooldown-gated so heat doesn't
leak between phases):
  idle       no OCR, just idle sampling (the baseline everything is compared
             against; what the laptop does when nothing runs)
  cpu        heimdall pre-fix engine: RapidOCR on onnxruntime, default threads
             (pins all cores -> heat/battery problem)
  cpu-capped heimdall engine with ORT intra=2 / inter=1 (current main)
  npu        OpenVINO static-shape on the NPU (proto session)

Metrics per mode:
  wall_secs        how long the workload took
  cpu_secs         process CPU-seconds (battery proxy: joules ~= cpu_secs * W)
  cpu_load_ratio   cpu_secs / wall (cores pinned, roughly)
  temp start/mean/peak, sampled from /sys/class/thermal/thermal_zone7 (TCPU)
  p50/p95 latency  per-frame, only for engine modes

No RAPL: energy_uj is root-only (0400) on this box, so temp profile + CPU
seconds are the honest proxies. Fan curve affects temp; cooldown gates and
alternating idle baselines keep the comparison fair.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

logging.disable(logging.INFO)
os.environ.setdefault("OPENVINO_LOG_LEVEL", "ERROR")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_ocr_npu as B  # NpuOpenVINOSession, _patch_engines, build helpers

THERMAL = Path("/sys/class/thermal/thermal_zone7/temp")
COOLDOWN_TEMP_C = 50.0
COOLDOWN_MAX_S = 300.0

CAPPED_PARAMS = {
    "EngineConfig.onnxruntime.intra_op_num_threads": 2,
    "EngineConfig.onnxruntime.inter_op_num_threads": 1,
}


def read_temp_c() -> float:
    try:
        return int(THERMAL.read_text().strip()) / 1000.0
    except OSError:
        return float("nan")


class TempSampler:
    """Sampling thread: temp every 0.5 s, start/end sync'd to the run."""

    def __init__(self):
        self._stop = threading.Event()
        self.samples: list[tuple[float, float]] = []  # (t_abs, temp_c)

    def __enter__(self):
        self._stop.clear()
        self.samples.clear()
        self._th = threading.Thread(target=self._run, daemon=True)
        self._th.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            self.samples.append((time.monotonic(), read_temp_c()))
            time.sleep(0.5)

    def __exit__(self, *exc):
        self._stop.set()
        self._th.join(timeout=2.0)

    def stats(self, t0: float, t1: float) -> dict:
        in_run = [t for (ta, t) in self.samples if t0 <= ta <= t1]
        before = [t for (ta, t) in self.samples if ta < t0]
        start = before[-1] if before else float("nan")
        if not in_run:
            return {"start_c": round(start, 1), "mean_c": None, "peak_c": None}
        return {
            "start_c": round(start, 1),
            "mean_c": round(float(np.mean(in_run)), 1),
            "peak_c": round(float(np.max(in_run)), 1),
        }


def cooldown_to(t0: float):
    """Wait until TCPU cools back to the pre-run baseline (or timeout)."""
    if t0 is None or t0 != t0:
        t0 = COOLDOWN_TEMP_C
    deadline = time.monotonic() + COOLDOWN_MAX_S
    while time.monotonic() < deadline:
        if read_temp_c() <= t0:
            return
        time.sleep(5)


def build_engine(mode: str):
    B._patch_engines()
    params = {}
    for task, fname in B.MODEL_FILES.items():
        params[f"{task.capitalize()}.model_path"] = str(B.MODELS_DIR / fname)
    if mode == "cpu":
        B.NPU_ACTIVE = False
        return B.RapidOCR(params=params)
    if mode == "cpu-capped":
        B.NPU_ACTIVE = False
        params.update(CAPPED_PARAMS)
        return B.RapidOCR(params=params)
    B.NPU_ACTIVE = True
    return B.RapidOCR(params=params)


def run_mode(mode: str, corpus: list[bytes], n_frames: int, baseline_temp: float) -> dict:
    out: dict = {"mode": mode}

    sampler = TempSampler()
    with sampler:
        t0 = time.monotonic()
        if mode == "idle":
            # idle run = one cooldown window's worth of doing nothing
            while time.monotonic() - t0 < 60:
                time.sleep(5)
            t1 = time.monotonic()
            out.update(sampler.stats(t0, t1))
            out["wall_secs"] = round(t1 - t0, 1)
            out["cpu_secs"] = 0.0
            out["cpu_load_ratio"] = 0.0
            out["n_frames"] = 0
            return out

        import resource

        engine = build_engine(mode)
        r0 = resource.getrusage(resource.RUSAGE_SELF)
        lat = []
        failures = 0
        for i in range(n_frames):
            try:
                s = time.perf_counter()
                engine(corpus[i % len(corpus)])
                lat.append((time.perf_counter() - s) * 1000.0)
            except Exception:
                failures += 1
        r1 = resource.getrusage(resource.RUSAGE_SELF)
        t1 = time.monotonic()
        cpu_secs = (r1.ru_utime + r1.ru_stime) - (r0.ru_utime + r0.ru_stime)

        arr = np.array(lat)
        out.update(sampler.stats(t0, t1))
        out["wall_secs"] = round(t1 - t0, 1)
        out["cpu_secs"] = round(cpu_secs, 2)
        out["cpu_load_ratio"] = round(cpu_secs / (t1 - t0), 2)
        out["n_frames"] = len(lat)
        out["failures"] = failures
        if arr.size:
            out["p50_ms"] = round(float(np.percentile(arr, 50)), 1)
            out["p95_ms"] = round(float(np.percentile(arr, 95)), 1)
            out["mean_ms"] = round(float(arr.mean()), 1)

        # per-mode compile stats (NPU)
        if mode == "npu":
            for sess_name in ("text_det", "text_cls", "text_rec"):
                sess = getattr(engine, sess_name, None)
                if sess is not None:
                    sess = sess.session
                    if hasattr(sess, "_compiles"):
                        out[f"{sess_name}.compiles"] = sess._compiles
                        out[f"{sess_name}.compile_secs"] = round(sess._compile_secs, 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--modes", default="idle,cpu,cpu-capped,npu")
    args = ap.parse_args()

    corpus = [p.read_bytes() for p in sorted(args.corpus.glob("*.jpg"))]
    print(f"corpus: {len(corpus)} frames; modes: {args.modes}; "
          f"frames/mode: {args.frames}", flush=True)

    import importlib.metadata as md
    print(f"versions: rapidocr {md.version('rapidocr')}, "
          f"onnxruntime {md.version('onnxruntime')}, "
          f"openvino {md.version('openvino')}", flush=True)
    print(f"initial TCPU: {read_temp_c():.1f}C", flush=True)

    results = []
    idle_baseline = None
    for mode in args.modes.split(","):
        if idle_baseline is not None:
            print(f"\n-- cooldown to {idle_baseline}C --", flush=True)
            cooldown_to(idle_baseline)
            print(f"   TCPU now {read_temp_c():.1f}C", flush=True)
        print(f"\n== {mode} ==", flush=True)
        res = run_mode(mode, corpus, args.frames, idle_baseline)
        print(json.dumps(res, indent=1), flush=True)
        if mode == "idle":
            idle_baseline = res.get("mean_c") or res.get("start_c")
        results.append(res)

    summary = {"modes": results, "thermal_zone": str(THERMAL),
               "rapidocr": md.version("rapidocr"),
               "onnxruntime": md.version("onnxruntime"),
               "openvino": md.version("openvino")}
    if args.out:
        args.out.write_text(json.dumps(summary, indent=2))
        print(f"\nsaved: {args.out}", flush=True)


if __name__ == "__main__":
    main()
