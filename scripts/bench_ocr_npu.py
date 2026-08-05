#!/usr/bin/env python3
"""Bench: NPU (OpenVINO static-shape) vs CPU (onnxruntime) for rapidocr, heimdall-style.

Ticket: Prototype: standalone NPU-vs-CPU OCR bench in the proto worktree (#67).

Both engines run the SAME rapidocr pipeline (det->cls->rec + postprocess) — only the
inference session differs. CPU = the exact heimdall engine (onnxruntime 1.28.0).
NPU = OpenVINO static-shape compiled models, shape->CompiledModel LRU cache, so
recompiles-on-shape-change are measured (the fog question).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import time
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np

logging.disable(logging.INFO)
os.environ.setdefault("OPENVINO_LOG_LEVEL", "ERROR")

import openvino as ov
from rapidocr import RapidOCR
from rapidocr.inference_engine.openvino.main import OpenVINOInferSession

MODELS_DIR = (
    Path(__import__("rapidocr").__file__).resolve().parent
    / "models"
)
MODEL_FILES = {
    "det": "PP-OCRv6_det_small.onnx",
    "cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "rec": "PP-OCRv6_rec_small.onnx",
}

CPU_SESSION_CFG = {}
NPU_SESSION_CFG = {}

_patched = False


class NpuOpenVINOSession(OpenVINOInferSession):
    """OpenVINO session compiled for the NPU; recompiles per input shape (LRU)."""

    cache_size = 6

    def __init__(self, cfg):
        self._core = ov.Core()
        model_path = cfg.get("model_path")
        if model_path is None:
            raise ValueError("model_path required for NPU bench session")
        self._model_path = Path(model_path)
        self._cache: OrderedDict[tuple, ov.CompiledModel] = OrderedDict()
        self._compiles = 0
        self._compile_secs = 0.0
        self._in_name = "x"
        self._verify_model(self._model_path)
        self.model = None
        self.session = None

    def _compiled_for(self, input_shape: tuple) -> ov.CompiledModel:
        key = tuple(input_shape)
        cm = self._cache.get(key)
        if cm is not None:
            self._cache.move_to_end(key)
            return cm
        t0 = time.perf_counter()
        model = self._core.read_model(self._model_path)
        model.reshape({self._in_name: input_shape})
        cm = self._core.compile_model(model, "NPU")
        dt = time.perf_counter() - t0
        self._compiles += 1
        self._compile_secs += dt
        self._cache[key] = cm
        if len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return cm

    def __call__(self, input_content: np.ndarray) -> np.ndarray:
        cm = self._compiled_for(input_content.shape)
        req = cm.create_infer_request()
        req.infer({cm.input(0).get_any_name(): input_content})
        return req.get_output_tensor().data

    # character list comes from the ONNX rt_info, same as the packaged engine
    def get_character_list(self, key: str = "character"):
        model = self._core.read_model(self._model_path)
        rt = model.get_rt_info()
        return rt["framework"][key].value.splitlines()

    def have_key(self, key: str = "character") -> bool:
        try:
            self.get_character_list(key)
            return True
        except Exception:
            return False


# make the generic det/cls/rec factories use our NPU session for engine_type=openvino
def _patch_engines():
    global _patched
    if _patched:
        return
    import rapidocr.ch_ppocr_cls.main as cls_m
    import rapidocr.ch_ppocr_det.main as det_m
    import rapidocr.ch_ppocr_rec.main as rec_m

    for mod in (det_m, cls_m, rec_m):
        orig = mod.get_engine

        def make(orig=orig, _self=sys.modules[__name__]):
            def get_engine(engine_type):
                if getattr(_self, "NPU_ACTIVE", False):
                    return NpuOpenVINOSession
                return orig(engine_type)

            return get_engine

        mod.get_engine = make()
    _patched = True


def build_engine(device: str):
    global NPU_ACTIVE
    _patch_engines()
    params = {}
    for task, fname in MODEL_FILES.items():
        params[f"{task.capitalize()}.model_path"] = str(MODELS_DIR / fname)
    NPU_ACTIVE = device == "npu"
    engine = RapidOCR(params=params)
    return engine


def load_corpus(corpus_dir: Path) -> list[bytes]:
    imgs = []
    for p in sorted(corpus_dir.glob("*.jpg")):
        data = p.read_bytes()
        imgs.append(data)
    return imgs


def cpu_usage_delta(fn, *a):
    import resource

    r0 = resource.getrusage(resource.RUSAGE_SELF)
    t0 = time.perf_counter()
    fn(*a)
    t1 = time.perf_counter()
    r1 = resource.getrusage(resource.RUSAGE_SELF)
    cpu_secs = (r1.ru_utime + r1.ru_stime) - (r0.ru_utime + r0.ru_stime)
    return t1 - t0, cpu_secs


def run_bench(device: str, corpus: list[bytes], passes: int, out: dict):
    t0 = time.perf_counter()
    engine = build_engine(device)
    init_secs = time.perf_counter() - t0
    out[f"{device}.init_secs"] = init_secs

    latencies = []
    texts_all = []
    failures = 0
    compile_secs = 0.0

    for pass_i in range(passes):
        for i, img in enumerate(corpus):
            t0 = time.perf_counter()
            try:
                res = engine(img)
            except Exception as e:
                failures += 1
                if failures <= 3:
                    import traceback

                    traceback.print_exc(limit=2)
                continue
            dt = time.perf_counter() - t0
            latencies.append(dt)
            if res is not None and hasattr(res, "txts") and res.txts:
                texts_all.append("\n".join(res.txts))
            else:
                texts_all.append("")
            if (i + 1) % 5 == 0:
                print(f"  [{device}] pass {pass_i + 1} frame {i + 1}/{len(corpus)} "
                      f"elapsed {time.perf_counter() - t0:.1f}s", flush=True)
    if device == "npu":
        compile_secs = 0.0
        # session compile stats live on the session instances
        for sess_name in ("text_det", "text_cls", "text_rec"):
            sess = getattr(engine, sess_name, None)
            if sess is not None:
                sess = sess.session
                if hasattr(sess, "_compiles"):
                    out[f"npu.{sess_name}.compiles"] = sess._compiles
                    out[f"npu.{sess_name}.compile_secs"] = round(sess._compile_secs, 2)
                    compile_secs += sess._compile_secs

    arr = np.array(latencies) * 1000.0
    out[f"{device}.frames"] = len(latencies)
    out[f"{device}.failures"] = failures
    out[f"{device}.p50_ms"] = round(float(np.percentile(arr, 50)), 1)
    out[f"{device}.p95_ms"] = round(float(np.percentile(arr, 95)), 1)
    out[f"{device}.p99_ms"] = round(float(np.percentile(arr, 99)), 1)
    out[f"{device}.mean_ms"] = round(float(arr.mean()), 1)
    out[f"{device}.min_ms"] = round(float(arr.min()), 1)
    out[f"{device}.max_ms"] = round(float(arr.max()), 1)
    out[f"{device}.recompile_secs_total"] = round(compile_secs, 2)

    # cpu usage over a single pass (wall/cpu ratio is the point, not count)
    pass_corpus = corpus
    wall, cpu = cpu_usage_delta(lambda: [engine(img) for img in pass_corpus])
    out[f"{device}.wall_secs_3pass"] = round(wall, 2)
    out[f"{device}.cpu_secs_3pass"] = round(cpu, 2)
    out[f"{device}.cpu_load_ratio"] = round(cpu / wall, 2) if wall else None
    return "\n".join(texts_all)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--passes", type=int, default=2)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    corpus = load_corpus(args.corpus)
    if not corpus:
        print("empty corpus")
        sys.exit(1)
    print(f"corpus: {len(corpus)} frames, {args.passes} passes")

    out: dict = {"corpus": str(args.corpus), "passes": args.passes}

    print("\n== CPU (onnxruntime 1.28.0, heimdall engine) ==")
    cpu_texts = run_bench("cpu", corpus, args.passes, out)
    print("==", json.dumps({k: v for k, v in out.items() if k.startswith("cpu.")}, indent=1))

    print("\n== NPU (OpenVINO static-shape) ==")
    npu_texts = run_bench("npu", corpus, args.passes, out)
    print("==", json.dumps({k: v for k, v in out.items() if k.startswith("npu.")}, indent=1))

    same = cpu_texts == npu_texts
    out["text_identical"] = bool(same)
    print(f"\ntext output identical: {same}")

    if args.out:
        args.out.write_text(json.dumps(out, indent=2))
        print(f"saved: {args.out}")


if __name__ == "__main__":
    main()
