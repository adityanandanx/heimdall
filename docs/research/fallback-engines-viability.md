# Ticket #14 — Fallback screen-content engines: can they run on THIS machine?

Reference for the v2 replacement-pipeline prototype tickets. Everything here was verified
on this machine (or is cited from a primary source — repo README / `man tesseract` / the
package itself). Nothing was benchmarked; latency/memory figures below are primary-source
claims only, or explicitly "measure in prototype".

## 0. Machine snapshot (verified live)

| item | value |
|---|---|
| CPU | Intel Core Ultra 9 185H, 16 threads, x86_64 (`/proc/cpuinfo`) |
| RAM | 30.8 GiB (`/proc/meminfo`: 32274652 kB) |
| GPU | Intel Arc (Meteor Lake-P) — **Vulkan-only, no CUDA** (`lspci`, `vulkaninfo` 1.4.350) |
| GPU VRAM | 15.7 GiB total / **11.3 GiB free** (`llama-server --list-devices`: `Vulkan0: Intel(R) Arc(tm) Graphics (MTL)`) |
| OpenCL | Intel NEO OpenCL 3.0 available (`clinfo`) |
| llama-server | **10182 (afeebe103b)** at `/usr/bin/llama-server`, serving gemma-4-E2B QAT q4_0 on :8080, Vulkan `-ngl 99`, `--no-mmproj`, 4 slots (`/props`) |
| Python | system 3.14.6 (PIL 12.3.0, numpy 2.5.1, `gi`/Atspi 2.60 OK); heimdall venv **3.11.15** (no torch/onnx/cv2/rapidocr installed) |
| tesseract | 5.5.3 (leptonica 1.87, AVX2), langs `afr eng osd` |

Network & cache characterization:

- **Network works right now.** `pip download requests` succeeded; HTTPS to pypi.org and
  huggingface.co both returned 200 (tested 2026-08-02). `gh` 2.97.0 works. So "install
  needs network" is live-viable, not a hard blocker — but vendor wheels for robustness.
- **HF token present** (`~/.cache/huggingface/token`); surya-2 repos return 200 even
  without a token (public).
- **uv cache 26G** holds real ML wheels: `torch 2.10.0-3-cp311` (full), `torch 2.13.0-cp313`,
  `onnxruntime 1.28.0-cp313`, `opencv-python 4.13.0.92/5.0.0.93`, `rapidocr 3.8.4/3.9.1`,
  `openvino 2026.2.0-cp311`, `timm`, `accelerate`. **pip cache 4.7G has no ML wheels.**
- **Offline `uv` resolution is unreliable**: `--offline` fails even for cached wheels
  (stale index metadata picks uncached versions; cp311 onnxruntime is simply absent). Treat
  offline as a dead end for now; the network path is the one to depend on.

## 1. Verdict at a glance

| candidate | install | CPU viable | notes |
|---|---|---|---|
| OmniParser-v2 | network (weights ~1.4GB, pip deps) | yes, slow | Florence-2 + YOLOv9-E; UI-icon parser, not plain OCR |
| RapidOCR v3 (onnxruntime) | network (models ship in the wheel) | **yes, fast** | torch-free; **VERIFIED running here** |
| Surya 2 | network (pip + weights ~1.5GB) | yes, slow | VLM OCR; reuses this machine's `llama-server` |
| tuned tesseract | none (installed) | yes | 4.3s/frame full-res already measured (ticket #5) |
| Gemma-4-E2B vision (mmproj) | none (mmproj cached) | via Arc Vulkan | **VERIFIED loads** (throwaway server, then killed) |

## 2. OmniParser-v2 (microsoft/OmniParser)

A UI-icon/screen-element *parser*, not an OCR engine: YOLO "icon_detect" finds regions, a
Florence-2 caption model describes each crop (text included). Text-heavy screens get
crop-by-crop Florence captions. Source: repo README + `util/utils.py` (fetched
2026-08-02).

- **(a) install** — network. `pip install -r requirements.txt` (torch, torchvision,
  transformers, ultralytics, supervision, numpy==1.26.4 pinned, plus easyocr/paddleocr/
  gradio/streamlit that the core v2 path doesn't need). Nothing usable in local caches for
  the venv's py3.11 (ultralytics/easyocr/paddleocr absent; torch cp311 wheel is cached but
  offline resolution still fails — see §0).
- **(b) CPU** — yes. `util/utils.py:66` loads Florence-2 with `torch_dtype=torch.float32`
  when no device is given; YOLO runs under torch. No CUDA gate. QoL: moderate/slow.
- **(c) latency/memory** — no official CPU benchmark in the README (claims are grounding
  accuracy, ScreenSpot-Pro 39.5%). Memory class: torch + Florence-2-base fp32 (1.08GB
  weights) ≈ 3–4GB RSS. Weights: `microsoft/OmniParser-v2.0` —
  `icon_caption/model.safetensors` **1.08GB** (Florence-2-base) +
  `icon_detect_v3/model.pt` **281MB** YOLOv9-E (MIT, HF PR #37; main branch still ships the
  40MB v1.5 ultralytics detector, AGPL). Total ≈ **1.4GB download**.
- **(d) prototype one-liner**:
  `uv pip install --python .venv/bin/python torch torchvision transformers huggingface_hub supervision ultralytics opencv-python numpy==1.26.4`
  then clone repo, `huggingface-cli download microsoft/OmniParser-v2.0 icon_caption/model.safetensors icon_detect_v3/model.pt --revision refs/pr/37 --local-dir weights`,
  and drive `util/omniparser.py`.

License note: v2 `icon_detect_v3` is MIT; the older ultralytics-based detectors were AGPL.

## 3. RapidOCR v3 — `rapidocr` (onnxruntime engine)

The `rapidocr_onnxruntime` v2 package was renamed/merged into `rapidocr` v3 with pluggable
engines (onnxruntime / openvino / paddle / mnn / tensorrt / pytorch — `inference_engine/`,
confirmed in the installed package). Torch-free.

- **(a) install** — network for the heimdall venv: `rapidocr==3.9.1` wheel is in the uv
  cache but `onnxruntime` cp311 is NOT (only cp313); offline resolution fails. Online:
  **verified working** — installed `rapidocr 3.9.1 + onnxruntime` into a scratch py3.11
  venv and ran CPU inference.
- **(b) CPU** — yes, native. Default engine `onnxruntime` with `use_cuda: false`; also has
  an OpenVINO engine (CPUID-friendly). **No model download**: default models ship inside
  the wheel (`models/ch_ppocr_mobile_v2.0_cls_mobile.onnx` 0.6MB, `PP-OCRv6_det_small.onnx`
  9.5MB, `PP-OCRv6_rec_small.onnx` 21MB). Larger PP-OCRv4 models download from
  modelscope.cn on request (reachable, returned 200).
- **(c) latency/memory** — README/docs make no hard CPU ms claim; class: det+cls+rec
  ONNX small models ≈ hundreds of ms–low seconds for a 1920x1200 JPEG on 16 threads,
  <0.5GB RSS. Verify in prototype. Smoke test on this machine: OCR'd a rendered text image
  to `('Heimdall','fallback','test','12345')` with boxes, digits intact.
- **(d) prototype one-liner**:
  `uv pip install --python .venv/bin/python rapidocr onnxruntime && .venv/bin/python -c "from rapidocr import RapidOCR; o=RapidOCR(); print(o('/tmp/frame.jpg').txts)"`
  (API object: `.txts`, `.boxes`, `.elapse`).

## 4. Surya 2 (datalab-to/surya)

Architecture changed vs v1: **Surya 2 is a single ~650M VLM** doing layout + OCR + tables,
served by `vllm` (GPU) or `llama.cpp` (CPU/Apple Silicon); text-line *detection* is a
separate small torch model (EfficientViT). Source: `README.md` (fetched 2026-08-02).

- **(a) install** — network. `pip install surya-ocr` (0.22.1) resolves to torch 2.13.0 +
  torchvision + transformers 5.14.1 and drags in the full `nvidia-*`/`cuda-toolkit` wheel
  set (useless dead weight here, ~2–4GB) — use `uv pip install` and tolerate it, or ask
  datalab for a CPU-only extra. Weights: `datalab-to/surya-ocr-2` `model.safetensors`
  **1.37GB**, or the llama.cpp-ready `datalab-to/surya-ocr-2-gguf` (`surya-2.gguf` 1.27GB +
  `surya-2-mmproj.gguf` 205MB). Both repos public (200 unauthenticated). ~1.5GB download.
- **(b) CPU** — yes, explicitly supported: README says CPU/Apple Silicon run via the
  `llama-server` binary from llama.cpp — which this machine already has (v10182). Surya's
  `SuryaInferenceManager` auto-spawns one (or attach via
  `SURYA_INFERENCE_URL=http://host:port/v1`).
- **(c) latency/memory** — README throughput table (primary source): llama.cpp/Metal
  `--parallel 8` → **0.108 pages/s**, p50 **59.3s**/page, ~2400 tok/page @96DPI, ~30W. CPU
  here will be the same order; the 2B-gemma-sized gguf could offload to the Arc Vulkan
  backend instead (faster — measure). Memory: ~1.3GB model + torch det.
- **(d) prototype one-liner**:
  `uv pip install --python .venv/bin/python surya-ocr && SURYA_INFERENCE_BACKEND=llamacpp .venv/bin/surya_ocr frame.jpg --keep_server`
  (auto-spawns llama-server; keep the 8080 instance out of the way or set
  `SURYA_INFERENCE_URL`).

## 5. Tuned tesseract 5.5.3 (existing binary)

The known 4.3s/frame baseline (ticket #5) with headroom that's already measured.

- **(a) install** — none needed. `eng`+`afr`+`osd` traineddata present at
  `/usr/share/tessdata/` (`tesseract --list-langs`).
- **(b) CPU** — yes, it's the incumbent. AVX2 build.
- **(c) latency/memory** — measured (ticket #5): 4.3s full-res, 1.4s half-scale (loses
  small text), ~0.5s quarter (useless). 2x upscale: tesseract has no internal upscaler —
  resize the JPEG with PIL bicubic before feeding (`man tesseract`: `--dpi`,
  `user_defined_dpi`); cost ≈ proportional to pixels. Memory ~300MB.
- **(d) knobs that are available (verified)** — `--help-psm`: modes 0–13, notably `11
  sparse_text` for UI, `6 single_block`, `7 single_line`; `--help-oem`: 0 legacy / 1
  lstm_only / 2 combined / 3 default. Also `-c tessedit_char_whitelist`, `--user-words`,
  `--dpi`. One-liner:
  `tesseract frame.jpg stdout --psm 11 -l eng` (or pytesseract
  `image_to_data(..., output_type=DICT)` for word boxes → the FTS5 feed).

## 6. Gemma-4-E2B vision via llama.cpp mmproj on Vulkan

- **mmproj cached**: `.../gemma-4-E2B-it-qat-q4_0-gguf/snapshots/675cff42…/gemma-4-E2B-it-mmproj.gguf`
  → blob `021059c…` **986MB** (md5 1e486296…). Two other snapshots (1894d1fc…, 69536a21…)
  point at a different mmproj blob (`58c187…`, md5 5261410…). **Use the one the
  start-llama.sh snapshot references** (675cff42).
- **(a) install** — none. **Verified loadable on this build**: a throwaway
  `llama-server --mmproj … -ngl 99` on :8099 came up in 6s, `loaded multimodal model`, and
  `/props` reported `modalities: {vision: True, …}`; process then killed, the :8080
  instance untouched. `llama-cli` is text-only (`-mmproj` rejected) — server-only flag.
  Build 10182 is recent enough (Gemma-4 chat template, `--image-min/max-tokens`,
  `--vision-gemma-*-default` flags all present in `--help`).
- **(b) CPU/GPU** — Arc Vulkan `-ngl 99` (that's how the base model already runs); VRAM
  needs ~3.35GB base + ~1GB mmproj ≈ fits the 11.3GB free.
- **(c) latency/memory** — no official OCR latency claim to cite; a 2B VLM with one
  full-screen image is a handful of seconds of vision prefill + decode on Vulkan (measure).
  Not an OCR engine — a free-form VLM; good for structure/summary, not for exact small-text
  transcription.
- **(d) prototype one-liner** (requires restarting the server — prototype session's job):
  `llama-server -m …/675cff42…/gemma-4-E2B_q4_0-it.gguf --mmproj …/675cff42…/gemma-4-E2B-it-mmproj.gguf -ngl 99 -c 8192 --jinja --temp 0 --reasoning off --port 8080`
  then `POST /v1/chat/completions` with an `image_url` part.

## 7. Bonus notes for the v2 map (not ticket scope)

- **OpenVINO gemma vision models in the HF cache are incomplete** (`OpenVINO/gemma-3-4b-it-int4-cw-ov`, `gemma-4-E4B-it-int4-ov`: config/tokenizer only, no weight blobs) — not usable offline.
- **Docling layout models are already cached** and layout-relevant (not OCR): `docling-layout-heron` (164M), `docling-models` (342M), `granite-docling-258M` (506M) — candidates if the v2 pipeline wants layout boxes.
- HF-repo access sanity: `google/gemma-4-E2B-it-qat-q4_0-gguf` tree 200; modelscope.cn 200 (RapidOCR's alternate model host).

## Open questions for prototype tickets

- RapidOCR: measure real 1920x1200 JPEG latency vs tesseract's 4.3s.
- Surya 2: does the auto-spawned llama-server use the Arc Vulkan backend by default on this box, and what's actual pages/s?
- Gemma-4-E2B vision: does a full 1920x1200 region fit `--image-max-tokens` / context at 8192, and is output usable enough to be worth the restart?
