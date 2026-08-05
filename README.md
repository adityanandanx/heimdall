# heimdall

Local, screen-only memory for Hyprland. A capture daemon listens to Hyprland's
event socket and on window changes grim's the active-window region to JPEG and
reads the window's a11y tree (AT-SPI) into SQLite (FTS5 searchable); tesseract
is retired. Music and video are captured via MPRIS — video watch-sessions (VLC
with exact file paths, Chromium title-only for now) become first-class, searchable
memories. A FastAPI server (`127.0.0.1:3030`) serves search/frames/watch-sessions
and runs two **pipes** — a day recap and a time breakdown — through a local
Gemma 4 QAT model on the Intel Arc Vulkan backend. Nothing leaves the machine.

## Requirements

- Arch + Hyprland, `grim`, `playerctl`, `/usr/bin/llama-server`
- Vulkan GPU for the model (`-ngl 99`); see `scripts/start-llama.sh`
- `uv` for the dev/test toolchain
- Chromium/Electron must be launched accessibility-enabled (see Ops checklist)
- `yt-dlp` (pinned in the project venv) for YouTube caption transcripts
- `ffmpeg` for lazy ASR audio extraction; `faster-whisper` is optional (extra)

## Install

```sh
uv sync                    # core deps + yt-dlp (captions)
uv sync --extra asr        # + faster-whisper (lazy ASR for subtitle-less VLC files)
uv build          # or: uv pip install -e .
```

Entry point: `heimdall` (CLI), `heimdall serve` (API + scheduler).

## Data layout

```
~/.heimdall/
  config.yaml            # tunables (see below)
  data.db                # SQLite (WAL): frames, tracks, events, watch_sessions, *_fts
  capture.heartbeat      # mtime/ts written by the capture daemon
  frames/YYYY/MM/DD/     # JPEGs, one per capture
  output/                # day-recap-*.md, time-breakdown-*.md
  logs/                  # optional, if you pass --log-dir
```

## Config (`~/.heimdall/config.yaml`, tunables only)

```yaml
data_dir: ~/.heimdall
api: {bind: 127.0.0.1, port: 3030}
llama_server: {base_url: http://127.0.0.1:8080, model: gemma-4-E2B-it-qat-q4_0}
capture: {debounce_s: 1.5, min_interval_s: 10, keepalive_min: 5, extract_workers: 1}
watch: {pause_ends_session_s: 60, poll_interval_s: 30}
scheduler: {day_recap: "0 23 * * *", time_breakdown: "5 23 * * *"}
rules: {window_class_category: {sidra: Music, mpv: Movies}}
observability: {enabled: true}
```

Missing file/keys → code defaults. Langfuse keys are env-only (`LANGFUSE_*`).
Observability defaults to **enabled**, but stays a no-op until the `langfuse`
package is installed and `LANGFUSE_HOST`/`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`
are set — capture/OCR are never traced, only pipe runs.

## Run (plain scripts — no systemd)

```sh
scripts/start-llama.sh                    # model server, Vulkan, foreground
scripts/start-capture.sh --log-dir ~/.heimdall/logs   # capture daemon
heimdall serve                            # API + scheduler (23:00/23:05 pipes)
heimdall status                           # down-detector
```

Watch-session preview: `http://127.0.0.1:3030` (served by the API, loopback
only) — a read-only, auto-refreshing list of watch-sessions (title, source,
watched range, wall span, transcript when present).

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
- [ ] play/pause music → `select * from tracks;` rows appear with `playing`/`paused`
- [ ] `heimdall serve` starts; `curl -s localhost:3030/health` → ok
- [ ] `heimdall status` shows server ok, capture alive, llama up, today's frame
  count, extraction mode (a11y/ocr), alive MPRIS players, the last watch-session
  and pending ASR jobs
- [ ] `heimdall search <word-you-saw>` returns a frame with a snippet and score
- [ ] `heimdall recap yesterday` writes `output/day-recap-YYYY-MM-DD.md` with front matter (`date, range, generated_at, frame_count, trace_url`) and all three sections, no `ValidationError`
- [ ] `heimdall breakdown --days 2` writes `output/time-breakdown-{endday}-2d.md` with summed minutes per category
- [ ] rerun `heimdall run day-recap` overwrites the same-day file (idempotent)

## Tests

```sh
uv run pytest tests/ -q
```

Seams tested: HTTP API (FTS search/ranking, frames, pipes, watch-sessions),
pipe parse/render + deterministic merge, capture event/span math, the MPRIS
watch-session state machine. The real llama-server/Vulkan path and OCR
accuracy are verified via the checklist above, not unit tests.
