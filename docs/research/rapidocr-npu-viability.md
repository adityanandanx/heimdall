# Ticket #66 — NPU path for bundled RapidOCR ONNX models (OpenVINO on Lunar Lake)

Research for the Map: NPU engine — run RapidOCR on the Lunar Lake NPU (proto worktree)
(map #65). Everything here was verified **live on this machine** or cited from primary
sources (official docs / PyPI / the installed package source). The onset real latency
numbers below were measured in the proto worktree (`proto/rapid-ocr-npu`).

## 0. Machine snapshot (verified live)

| item | value |
|---|---|
| CPU | Intel Core Ultra 200H/200V (Lunar Lake), x86_64 |
| NPU | Core Ultra 200H/200V NPU — lspci `00:0b.0` (PCI 8086:7D1D), driver `intel_vpu`, `/dev/accel/accel0` (`crw-rw---- root render`) |
| Kernel | 6.12.69-2-cachyos-lts-lto; user in `render` group → read/write on `/dev/accel/accel0` confirmed |
| OpenVINO (system) | 2026.2.1 at `/opt/intel/openvino` (has `libopenvino_intel_npu_plugin.so` + compiler) |
| OpenVINO (venv) | **2026.3.0** via `uv pip install openvino` in the proto worktree venv |
| onnxruntime-openvino | **1.24.1** wheel (bundles OpenVINO 2025.4.1) — official Intel/Microsoft package |
| rapidocr | **3.9.2** (existing heimdall dep, venv) — bundled models `PP-OCRv6_det_small`, `PP-OCRv6_rec_small`, `ch_ppocr_mobile_v2.0_cls_mobile` in `rapidocr/models/*.onnx` |

State pinned during timing runs: NPU was the only load; llama-server (Vulkan) idle on
`:8080`. All latencies below are **first-call-after-compile** and **steady-state p50** of
the raw model inference (no JPEG decode, no det→cls→rec orchestration — that's the
prototype's job, ticket #67).

## 1. Verdict at a glance

| approach | NPU viable? | notes |
|---|---|---|
| `onnxruntime-openvino` EP, `device_type=NPU`, with `reshape_input` | **No on rec** | det + cls compile fine; **rec fails** even with `reshape_input` on static shapes (`Input for tensor name 'x' is not found` — OpenVINO EP reshape-input quirk; fails identically with `device_type=CPU`). |
| OpenVINO EP, dynamic shapes, no reshape | **No** | rec → vpux compiler crash: unbounded dims on `Add.206` / `Transpose.7`, `LLVM ERROR: Failed to infer result type`. |
| **Direct OpenVINO, static `ov.Shape`, `core.compile_model(..., "NPU")`** | **YES — the working path** | all three models compile + run; quick in output table below. |

The `onnxruntime-openvino` EP swap the onnxruntime code path reaches for is a **dead
ender for the rec model on its dynamic shape** — the EP CRUD does not accept the rec
graph. The working path is **OpenVINO-direct with static shapes** (convert/static-reshape
once, compile on NPU, cache compiled blob). That also matches Intel's documented advice:
OpenVINO EP `reshape_input` is "required for optimal NPU memory allocation", and the NPU
plugin re-compiles per shape — the det model's arbitrary window dims would recompile
per-window otherwise.

## 2. Researched/verified claims

1. **OpenVINO EP officially targets the NPU** (onnxruntime.ai/docs/.../OpenVINO-EP):
`device_type` supports `CPU, NPU, GPU`; NPU precision is FP16; EP falls back to CPU
for NPU-unsupported ops; provider options migrated to `load_config` since ORT 1.23. Confirmed
the wheel bundles OpenVINO so no separate system install needed on Linux (PyPI page: "Linux
Wheels come with pre-built libraries of OpenVINO 2025.4.1").
   - Caveats from provider docs: onnx `dynamic shapes bounds via `[lower..upper]`, fixed
   `input_name[fixed]`, `cache_dir` — all exactly the knobs the NPU path wants lost in the EP swap.
   **Verified the EP **cannot reshape the rec model (even CPU device_type) → use direct instead.**

2. **RapidOCR 3.9.2 packages an OpenVINO engine** (`rapidocr/inference_engine/openvino/`,
`OpenVINOInferSession) — `main.py:65` **hardcodes `device_name="CPU"`** with
only a CPUDeviceCfg. It proves RapidOCR the OpenVINO family exists in-tree and the seam for NPU is
thin — patch the device string (and feed static models. Uses same OrdClass subgraphs.
3. **Bundled ONNX = PaddleOCR v6/v5 family** (`rapidocr/models/`). Detection has
dynamic H,W; rec has dynamic batch+W (input `x` [Dyn,3,48,Dyn], output `(Dyn, Reshape_470_o0__d2, 18710)`) — exactly what clegend NPU compensation.

## 3. Recommended approach (for the prototype, ticket #67)

Pre-opening: static-shape OpenVINO, NPU plugin, runtime = the working thing. Options:

**(A) Direct OpenVINO (recommended)** — build a small OpenVINO-based engine holding three
pre-compiled `CompiledModel`s (det/cls/rec at a fixed max window shape or a small cache
of shape→blob), encode the same PP-OCR preprocessing from rapidocr's utils, and run
det→classify→rec with the same postprocessing (likely reuse rapidocr's own per-crop
routines and `rapidocr.utils`). The model .pb → `core.read_model(onnx)` →
`m.reshape({"x": [1,3,H,W]})` → `core.compile_model(m, "NPU")`. Measured here:

| model | static shape | compile (cold) | steady p50 |

| rec | (1,3,48,320) | 0.73s | **64 ms/frame ~15..16 FPS** — for TN41 stream captures |
| det | (1,3,736,1312) | 1.84s | **46 ms/frame** |
| cls | (1,3,48,192) | 0.76s | **2.5 ms** |

(the corresponding CPU (ort EP CPU measured) latencies: … to be filled by bench in
#67.)

One alternative that keeps rapidocr's whole pipeline untouched: **patch the packaged
`OpenVINOInferSession`** (device_name="NPU") and pass the models as static-IR, still via
`RapidOCR(params=...)` — small diff, reuses all det/postproc/rec wiring. Decide
between these in the prototype; the bench above is the substrate either way.

## 3. Open questions / risks

- **Shape-choice**: NPU recompiles per shape. Real window sizes vary (e.g. 1920×1080 →
  det input ~(1,3,736,1312)); a static-lobby will `compile` per new shape unless we fix a
  canvas + resize (rapidocr's dichotom for PP-OCR is render-time resize) or a small
  pre-compiled shape cache. Risk to quantify in #67: cost of one recompile (≈1.8 s) times
  per-window shape changes in a capture session.
- **FP16 on NPU**: `precision` hint/`INFERENCE_PRECISION_HINT` — likely automatic; verify
  accuracy on real frames in #67.
- **Driver bridge**: `/dev/accel/accel0` open works since `render` membership; NPU plugin
  from the venv openvino reads it; no system conflict observed (llama on Vulkan/GPU
  untouched).
- **rapidocr wrapper + custom engine**: which seam level (wholesale replace vs patch the
  packaged engine) — prototype ticket decides;  `CaptureTools.rapid_ocr` in heimdall is
  the seam regardless.

Verify → prototype branch: `proto/rapid-ocr-npu`, bench in `scripts/bench_ocr_npu.py`.

[Source worktree/branch: `research/rapid-ocr-npu-path`]