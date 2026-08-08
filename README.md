# heimdall

Local, screen-only memory for Hyprland. A capture daemon listens to Hyprland's
event socket and on window changes grim's the active-window region to JPEG and
reads the window's a11y tree (AT-SPI) into SQLite (FTS5 searchable). When a
window is blind (no a11y text) RapidOCR reads the pixels instead — via the NPU
(OpenVINO) when it's usable, else CPU; tesseract is retired. Music and video are
captured via MPRIS — video watch-sessions (VLC with exact file paths, Chromium
URLs resolved by a native-messaging extension) become first-class, searchable
memories. A FastAPI server (`127.0.0.1:3030`) serves search / frames /
watch-sessions / settings and runs two **pipes** — a day recap and a time
breakdown — through a local Gemma 4 QAT model on the Intel Arc Vulkan backend.
Nothing leaves the machine.

The UI is the **Tauri 2 desktop client** (`desktop/`): day timeline, search,
sessions, status and a settings surface that writes heimdall's own `config.yaml`
live — OCR engine, exclusions, window rules, scheduled pipes, pause, forget —
with no restart: the daemon and server hot-reload on a `settings.dirty` marker.

## Requirements

- Arch + Hyprland, `grim`, `playerctl`, `/usr/bin/llama-server`
- Vulkan GPU for the model (`-ngl 99`); see `scripts/start-llama.sh`
- `uv` for the dev/test toolchain
- Chromium/Electron must be launched accessibility-enabled (see Ops checklist)
- `yt-dlp` (pinned in the project venv) for YouTube caption transcripts
- `ffmpeg` for lazy ASR audio extraction; `faster-whisper` is optional (extra)
- NPU OCR (optional): an Intel NPU device + OpenVINO — without one, `auto`/`npu`
  engines fall back to CPU (the client shows an amber hint)
- Desktop client: Node + pnpm (+ Rust for `tauri build`)

## Install

```sh
uv sync                    # core deps + yt-dlp (captions) + OCR engines (rapidocr, openvino)
uv sync --extra asr        # + faster-whisper (lazy ASR for subtitle-less VLC files)
uv build          # or: uv pip install -e .
cd desktop && pnpm install # desktop client (Tauri 2)
```

Entry point: `heimdall` (CLI), `heimdall serve` (API + scheduler).

## Data layout

```
~/.heimdall/
  config.yaml            # tunables (see below) — the single source of truth
  data.db                # SQLite (WAL): frames, tracks, events, watch_sessions, *_fts
  capture.heartbeat      # mtime/ts written by the capture daemon
  capture.engine         # active OCR engine (npu|cpu) published by the daemon
  settings.dirty         # marker; touched on /settings writes, triggers hot-reload
  frames/YYYY/MM/DD/     # JPEGs, one per capture
  captions/              # cached caption content, keyed by media_id
  output/                # day-recap-*.md, time-breakdown-*.md
  logs/                  # optional, if you pass --log-dir
```

## Config (`~/.heimdall/config.yaml`, tunables only)

```yaml
data_dir: ~/.heimdall
api: {bind: 127.0.0.1, port: 3030}
llama_server: {base_url: http://127.0.0.1:8080, model: gemma-4-E2B-it-qat-q4_0}
capture: {debounce_s: 1.5, min_interval_s: 10, keepalive_min: 5, extract_workers: 1,
          extraction: auto, change_gate: true, ocr_engine: auto, paused: false}
watch: {pause_ends_session_s: 60, poll_interval_s: 30, media_resolver: extension,
        excluded_players: [sidra], excluded_windows: []}
scheduler: {day_recap: "0 23 * * *", time_breakdown: "5 23 * * *"}
rules: {window_class_category: {sidra: Music, mpv: Movies}}
observability: {enabled: true}
```

Missing file/keys → code defaults. Langfuse keys are env-only (`LANGFUSE_*`).
Observability defaults to **enabled**, but stays a no-op until the `langfuse`
package is installed and `LANGFUSE_HOST`/`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`
are set — capture/OCR are never traced, only pipe runs.

### Live settings (the spine)

`GET /settings` returns the full writable surface (12 keys) read live from
config.yaml; `POST /settings {key, value}` writes one key through to the file
(unknown keys preserved, atomic write) and touches `settings.dirty`. The capture
daemon (15s poll) and the server re-read config live:

- `capture.ocr_engine` — `auto` (NPU when usable, else CPU) | `npu` | `cpu`;
  `/status` reports `capture.ocr_engine {configured, active}` so a fallback is
  visible (amber hint in the client)
- `capture.extraction` — `auto` (a11y text, else OCR) | `a11y` only | `ocr` only
- `capture.paused` — full-stop pause: no frames, extraction, watch sessions or ASR
- `watch.excluded_players` / `watch.excluded_windows` — MPRIS players and window
  classes that never produce frames/sessions (scheduled captures only — manual
  captures bypass the gate)
- `watch.media_resolver` — `extension` (default) | `cdp` for Chromium URLs
- `scheduler.day_recap` / `scheduler.time_breakdown` — cron, or **null = pipe
  disabled**; edits re-arm the job live (`/status` shows next runs)
- `observability.enabled` — tracing toggle, applied live
- `rules.window_class_category` — window class → one of the 8 fixed breakdown
  categories

`POST /forget {categories, start, end}` hard-deletes frames / sessions /
transcripts in a time window in one transaction (FTS stays consistent via AFTER
DELETE triggers; frame images and caption-cache files follow after commit).

## Run (plain scripts — no systemd)

```sh
scripts/start-llama.sh                    # model server, Vulkan, foreground
scripts/start-capture.sh --log-dir ~/.heimdall/logs   # capture daemon
heimdall serve                            # API + scheduler (23:00/23:05 pipes)
heimdall status                           # down-detector
cd desktop && pnpm tauri dev              # desktop client (the UI)
```

The API is loopback-only and **API-only** — there is no HTML UI; the desktop
client is a pure HTTP client with the server URL in Settings
(dev: `pnpm tauri dev`, prod bundle: `pnpm tauri build`).

Autostart is opt-in (default OFF) — one `exec-once` per piece in `hyprland.conf`:

```
exec-once = ~/heimdall/scripts/start-llama.sh > ~/.heimdall/logs/llama.log 2>&1
exec-once = ~/heimdall/scripts/start-capture.sh --log-dir ~/.heimdall/logs
exec-once = uv run heimdall serve > ~/.heimdall/logs/serve.log 2>&1
```

A crashed capture gaps data until noticed; scheduled pipes only run while
`serve` is up. Logs are per-terminal stdout/stderr or `~/.heimdall/logs/`.

## Ops checklist (launch prerequisites & installs)

Run once after setup; everything is a plain script, no service manager.

- [ ] **Chromium/Electron accessibility (a11y capture)**: launch the browser with
  `ACCESSIBILITY_ENABLED=1` and `--force-renderer-accessibility`, e.g.
  `exec-once = env ACCESSIBILITY_ENABLED=1 chromium --force-renderer-accessibility`
  (add the flag to your launcher's Exec line for other apps). Without it the a11y
  tree is empty and the window falls back to OCR.
- [ ] **Chromium URL resolution**: run `scripts/install-messenger-host.sh`, then
  load the built extension from `~/.heimdall/extensions/heimdall-messenger` via
  `chrome://extensions` (Developer mode → Load unpacked). No debug port needed.
  Only the legacy `watch.media_resolver: cdp` path requires Chrome started with
  `--remote-debugging-port`.
- [ ] **NPU OCR (optional)**: install the Intel NPU driver; `uv sync` already
  brings `openvino`. Without an NPU device, `auto`/`npu` fall back to CPU —
  visible via `heimdall status --json` → `capture.ocr_engine.active` and the
  client's amber hint.
- [ ] **yt-dlp venv**: captions need `yt-dlp` (pinned in the project venv via
  `uv sync`). Verify with `uv run python -c "import yt_dlp"`.
- [ ] **faster-whisper (optional)**: needed only when local-file (VLC) sessions
  have no caption track — `uv sync --extra asr`, then the `small` model downloads
  on first use. Without it, ASR jobs report unavailable and sessions stay
  title-only.
- [ ] **ffmpeg**: required for lazy ASR (`/usr/bin/ffmpeg`).
- [ ] **Autostart**: opt-in, OFF by default — add the `exec-once` lines above
  only if you want capture + pipes at login.

## CLI

```sh
heimdall search <q> [--window-class --start --end --limit --offset --json]
heimdall sessions [--player --start --end --limit --offset --json]
heimdall recap [today|yesterday|YYYY-MM-DD]
heimdall breakdown [day] [--days N] [--json]
heimdall status [--json]
heimdall capture [--json]
heimdall run <pipe> [--day today]
heimdall serve
```

`breakdown --days N` merges the last N day-files deterministically (no extra
LLM pass) into `output/time-breakdown-{endday}-{N}d.md`.

## Verification checklist (run once after setup)

- [ ] `scripts/start-llama.sh` starts; `curl -s localhost:8080/health` → ok; server log shows a **Vulkan** device (not CPU)
- [ ] `scripts/start-capture.sh` runs; switch windows → wait ~2s → `sqlite3 ~/.heimdall/data.db 'select count(*) from frames;'` grows; a frame's `ocr_text` is populated within ~5s (OCR worker)
- [ ] `cat ~/.heimdall/capture.engine` → `npu` or `cpu`; `heimdall status --json` → `capture.ocr_engine.active` matches
- [ ] play/pause music → `select * from tracks;` rows appear with `playing`/`paused`
- [ ] `heimdall serve` starts; `curl -s localhost:3030/health` → ok; `curl -s localhost:3030/settings` lists the 12 writable keys
- [ ] `curl -X POST localhost:3030/settings -d '{"key":"capture.ocr_engine","value":"cpu"}'` → daemon reloads; flip back to `auto`
- [ ] `heimdall status` shows server ok, capture alive, llama up, today's frame
  count, extraction mode + OCR engine (configured/active), alive MPRIS players,
  the last watch-session, scheduler next runs and pending ASR jobs
- [ ] `heimdall search <word-you-saw>` returns a frame with a snippet and score
- [ ] `heimdall recap yesterday` writes `output/day-recap-YYYY-MM-DD.md` with front matter (`date, range, generated_at, frame_count, trace_url`) and all three sections, no `ValidationError`
- [ ] `heimdall breakdown --days 2` writes `output/time-breakdown-{endday}-2d.md` with summed minutes per category
- [ ] rerun `heimdall run day-recap` overwrites the same-day file (idempotent)

## Tests

```sh
uv run pytest tests/ -q        # backend
cd desktop && pnpm test        # desktop client (Vitest + RTL, MSW)
```

Seams tested (backend): HTTP API (FTS search/ranking, frames, pipes,
watch-sessions, settings + forget), pipe parse/render + deterministic merge,
capture event/span math, the MPRIS watch-session state machine, the live
settings spine. The real llama-server/Vulkan path and OCR accuracy are verified
via the checklist above, not unit tests.
