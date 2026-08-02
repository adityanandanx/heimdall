# Heimdall — Local Screen & Audio Memory (Gemma 4 + LangGraph) Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replicate a stripped-down screenpipe on Arch/Hyprland: 24/7 local screen+audio capture → OCR + transcription → SQLite FTS5 → searchable via FastAPI, with LangGraph-driven AI pipes (day recap, time breakdown, meeting summary) powered by Gemma 4 running through llama.cpp.

**Architecture:** Event-driven capture (Hyprland IPC socket events → grim screenshot + tesseract OCR; PipeWire audio → faster-whisper) writes into a local SQLite FTS5 DB. A FastAPI server (localhost:3030) exposes search/frames/health. LangGraph `StateGraph` pipes run on schedule (APScheduler), query the DB via tools, and call llama-server (OpenAI-compatible, Gemma 4 12B QAT-Q4_0 on Intel Arc Vulkan) for summarization. CLI for interaction. No cloud, no telemetry, no Tauri UI (optional web UI later).

**Tech Stack:** Python 3.11 (uv venv), grim + tesseract + PipeWire/pw-record (system tools, all installed), faster-whisper, sqlite3 FTS5, FastAPI + uvicorn, LangGraph + langchain-openai, llama-server (already at /usr/sbin/llama-server v10182), Gemma 4 12B QAT GGUF (7 GB), Intel Arc Vulkan backend.

---

## Key Decisions (research-backed)

- **Model:** `lmstudio-community/gemma-4-12B-it-QAT-GGUF` → `gemma-4-12B-it-QAT-Q4_0.gguf` (7.0 GB). QAT is Google's recommended llama.cpp quant for Gemma 4 (vs plain Q4_K_M). Fits 19 GB free RAM; Vulkan offloads to Intel Arc iGPU.
- **Whisper:** `faster-whisper` (CTranslate2, CPU-friendly, no GPU build hassle on this box) — `small` or `base` model for MVP.
- **Event source:** Hyprland `$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket2.sock` — listen for `activewindow>>`, `workspace>>`, `openwindow>>`, `fullscreen>>`. Debounce to ~1 capture/5-10s max.
- **No a11y tree on Hyprland** (unlike macOS screenpipe) — OCR is the primary text layer, plus window class/title from hyprctl. This is the correct stripping decision.
- **No cloud, no telemetry, no sync, no MCP server in v1** — pure localhost.

## Stripped vs. kept (vs. screenpipe)

| screenpipe | heimdall |
|---|---|
| Accessibility tree capture | ❌ dropped — Hyprland has none; window titles + OCR |
| Event-driven capture | ✅ Hyprland socket2 events |
| OCR fallback | ✅ tesseract (primary now) |
| Whisper STT + diarization | ✅ faster-whisper, basic speaker labels |
| SQLite + FTS5 | ✅ same |
| REST API :3030 | ✅ FastAPI :3030 |
| Pipes = markdown agents (pi/claude-code) | ✅ **LangGraph StateGraph** pipes (Gemma 4) |
| MCP server | ⏸️ optional later |
| Tauri desktop app | ❌ CLI (+ optional web UI) |
| Cloud AI / Deepgram / PostHog / Sentry | ❌ all local, no telemetry |
| E2E sync / team / enterprise | ❌ dropped |

---

## Project Layout

```
~/stuff/heimdall/
├── pyproject.toml
├── README.md
├── config.yaml
├── src/heimdall/
│   ├── __init__.py
│   ├── config.py
│   ├── db.py                 # SQLite FTS5 schema + queries
│   ├── capture/
│   │   ├── __init__.py
│   │   ├── hypr_events.py    # socket2 listener
│   │   ├── screenshot.py     # grim + hyprctl window meta
│   │   ├── ocr.py            # tesseract wrapper
│   │   └── audio.py          # pw-record + faster-whisper
│   ├── server.py             # FastAPI app
│   ├── llm.py                # llama-server OpenAI client (Gemma 4)
│   ├── pipes/
│   │   ├── __init__.py
│   │   ├── base.py           # StateGraph builder
│   │   ├── day_recap.py
│   │   ├── time_breakdown.py
│   │   └── meeting_summary.py
│   ├── scheduler.py          # APScheduler wiring
│   └── cli.py                # typer CLI
├── scripts/
│   ├── start-llama.sh
│   ├── start-capture.sh
│   └── start-server.sh
└── tests/
    ├── test_db.py
    └── test_ocr.py
```

---

## Task 1: Project scaffold + venv

**Objective:** Create uv project, install deps, verify imports.

**Files:**
- Create: `~/stuff/heimdall/pyproject.toml`
- Create: `~/stuff/heimdall/src/heimdall/__init__.py`

**Step 1:** `mkdir -p ~/stuff/heimdall && cd ~/stuff/heimdall && uv init --python 3.11`
**Step 2:** `uv add fastapi uvicorn langgraph langchain-openai typer pyyaml apscheduler faster-whisper pillow`
**Step 3:** `uv add --dev pytest`
**Step 4:** Verify: `uv run python -c "import langgraph, fastapi, typer; print('ok')"` → `ok`

---

## Task 2: Config module

**Objective:** Load `config.yaml` with typed defaults.

**Files:**
- Create: `src/heimdall/config.py`
- Create: `config.yaml` (data dir, llm base_url `http://localhost:8080/v1`, model name, capture debounce, audio device)

**Verify:** `uv run python -c "from heimdall.config import load_config; print(load_config())"`

---

## Task 3: SQLite FTS5 layer

**Objective:** Schema + insert/search functions.

**Files:**
- Create: `src/heimdall/db.py`
- Test: `tests/test_db.py`

**Schema:**
```sql
CREATE TABLE frames(id INTEGER PRIMARY KEY, ts TEXT, monitor TEXT, window_class TEXT, window_title TEXT, image_path TEXT);
CREATE VIRTUAL TABLE texts USING fts5(frame_id, content, ts);
CREATE TABLE audio(id INTEGER PRIMARY KEY, ts TEXT, transcript TEXT, speaker TEXT, duration REAL);
```

**Verify:** `uv run pytest tests/test_db.py -v` → 3 passed

---

## Task 4: Capture — Hyprland events + grim + OCR

**Objective:** Listener captures screenshot + window meta on events, OCRs, writes to DB.

**Files:**
- Create: `src/heimdall/capture/hypr_events.py`
- Create: `src/heimdall/capture/screenshot.py`
- Create: `src/heimdall/capture/ocr.py`
- Test: `tests/test_ocr.py` (needs a sample PNG in tests/fixtures/)

**Step 1:** Write test that OCRs a fixture image → expects known text substring.
**Step 2:** Implement `ocr.py` (`tesseract` subprocess, `--psm 3`, eng).
**Step 3:** Implement `screenshot.py`: `grim -o <monitor> -t jpeg <path>` + `hyprctl activewindow -j` for class/title/workspace.
**Step 4:** Implement `hypr_events.py`: connect unix socket `.socket2.sock`, read lines, filter `activewindow>>|workspace>>|openwindow>>|fullscreen>>`, debounce ≥5 s, then capture+OCR+insert.
**Verify:** `uv run pytest tests/test_ocr.py -v` → PASS. Manual: run listener 30 s, `sqlite3 ~/.heimdall/data.db 'select count(*) from frames'` → >0.

---

## Task 5: Audio capture + transcription

**Objective:** Record system audio + mic in chunks, transcribe with faster-whisper, insert.

**Files:**
- Create: `src/heimdall/capture/audio.py`

**Step 1:** `pw-record --target <sink> /tmp/chunk.wav` for 30 s via subprocess (or `parec` with `--format=s16le` piped to WAV writer).
**Step 2:** `faster_whisper.WhisperModel("small", device="cpu")` → transcribe chunks (non-blocking, in worker thread).
**Step 3:** Insert into `audio` table with ts/speaker (speaker = "system" or "mic" source for MVP).

**Verify:** Record 15 s of audio, run transcribe, expect non-empty transcript in DB.

---

## Task 6: FastAPI server

**Objective:** REST API on :3030.

**Files:**
- Create: `src/heimdall/server.py`

**Endpoints:** `GET /health` → `{status:"ok"}`; `GET /search?q=&content_type=all|ocr|audio&limit=20&window=` → FTS5 results; `GET /frames?window_class=&range=` → frame list; `POST /pipes/run/{name}` → triggers pipe.

**Verify:** `uv run uvicorn heimdall.server:app --port 3030` then `curl localhost:3030/health` → `{"status":"ok"}`.

---

## Task 7: Gemma 4 via llama-server

**Objective:** Download model, start llama-server with Vulkan, verify OpenAI-compatible chat.

**Files:**
- Create: `scripts/start-llama.sh`
- Create: `src/heimdall/llm.py`

**Step 1:**
```bash
mkdir -p ~/models && cd ~/models
# 7 GB — user may need to run this if it's slow/large
huggingface-cli download lmstudio-community/gemma-4-12B-it-QAT-GGUF --include "gemma-4-12B-it-QAT-Q4_0.gguf"
```
**Step 2:** `scripts/start-llama.sh`:
```bash
/usr/sbin/llama-server \
  -m ~/models/gemma-4-12B-it-QAT-Q4_0.gguf \
  --host 127.0.0.1 --port 8080 \
  -ngl 99 -c 8192 --jinja
```
(`-ngl 99` → Vulkan offload to Arc; `--jinja` for correct Gemma 4 chat template)
**Step 3:** Verify:
```bash
curl localhost:8080/v1/chat/completions -d '{"model":"gemma-4-12B-it-QAT-Q4_0","messages":[{"role":"user","content":"say hi in 3 words"}]}'
```
**Step 4:** `llm.py` — `langchain_openai.ChatOpenAI(base_url="http://localhost:8080/v1", api_key="local", model="gemma-4-12B-it-QAT-Q4_0", temperature=0.3)`. **Gemma 4 CoT note:** model emits a `[Start thinking]` block before answers — set system prompt "Respond only with raw JSON. Do not include any thinking, analysis, or explanation." and post-strip `[Start thinking]...[/End thinking]` if present.

**Verify:** `uv run python -c "from heimdall.llm import llm; print(llm.invoke('hi').content)"`

---

## Task 8: LangGraph pipes

**Objective:** `StateGraph`-based pipes. Each pipe: `load` node (db tools) → `refine` (optional) → `summarize` (Gemma 4) → `output` (write markdown to ~/heimdall/output/).

**Files:**
- Create: `src/heimdall/pipes/base.py` — generic builder:
  ```python
  from langgraph.graph import StateGraph, START, END
  from typing import TypedDict

  class PipeState(TypedDict):
      query: str
      content_type: str
      time_range: str
      results: list
      summary: str
      output_path: str
  ```
  Nodes: `load(state) -> results`, `summarize(state) -> summary` (Gemma 4), `output(state) -> path`. Conditional edge: if no results → END early.
- Create: `day_recap.py` — query today's ocr+audio, summarize accomplishments/unfinished work.
- Create: `time_breakdown.py` — group frames by window_class over a range, Gemma 4 categorizes app→project/time.
- Create: `meeting_summary.py` — pull audio transcripts in range, summarize + key decisions + action items.

**Verify:** `uv run python -c "from heimdall.pipes.day_recap import build; g=build(); print(g.invoke({'time_range':'today'}))"` → summary dict with non-empty `summary`.

---

## Task 9: Scheduler + CLI

**Files:**
- Create: `src/heimdall/scheduler.py` — APScheduler: day-recap 19:00 daily, time-breakdown 21:00 daily, meeting-summary on demand.
- Create: `src/heimdall/cli.py` — typer: `sp search "query"`, `sp recap [today|yesterday]`, `sp breakdown --days 1`, `sp status`, `sp run <pipe>`.
- Create: `scripts/start-capture.sh` + `scripts/start-server.sh`.

**Verify:** `uv run sp status` → shows capture daemon + llama-server + DB size. `uv run sp recap today` → markdown summary file written.

---

## Task 10: Systemd user units + README

**Objective:** Autostart everything.

**Files:**
- Create: `~/.config/systemd/user/heimdall-capture.service`, `heimdall-server.service` (llama-server optional — start manually or via systemd too)
- Create: `README.md` (install, run, commands)

**Verify:** `systemctl --user enable --now heimdall-capture heimdall-server` → `systemctl --user status` both active; data accumulating after 2 min.

---

## Risks / Tradeoffs / Open Questions

- **Gemma 4 CoT overhead** → may emit thinking preamble; mitigation: system prompt + post-strip (Task 7). JSON reliability on 12B QAT should be good but test with `--temp 0.3`.
- **Intel Arc Vulkan on this llama.cpp build** (v10182, MESA experimental warning) — if `-ngl 99` crashes, fall back to CPU (`-ngl 0`) — 16 cores, Q4 12B ≈ 8-12 t/s, acceptable for batch pipes.
- **iGPU shares system RAM** — 7 GB model + whisper small + OS fits in 19 GB free, but watch memory during capture.
- **Storage growth** — ~20 GB/mo like screenpipe; add retention cleanup task if needed (NOT in v1 scope).
- **No multi-device sync, no browser-history capture, no keyboard input capture** in v1 — all stripped by design.
- **Open question:** do you want keyboard input capture (screenpipe captures it) — recommend NO for v1 (privacy + complexity).
- **Open question:** basic web UI worth it in v1? Recommend CLI-only first, web later.

## Verification Checklist (end-to-end)

1. `systemctl --user status heimdall-capture heimdall-server` → active
2. `curl localhost:3030/health` → ok
3. Work 10 min → `sp search "what I did"` returns OCR/transcript hits
4. `sp recap today` → markdown with real summary from Gemma 4
5. `sp breakdown --days 1` → app time categories
6. Full pipeline idle CPU < 15% (event-driven should be ~5-10%)
