# Ticket #5 — Event-driven Hyprland capture: measured findings

Prototype in `prototypes/capture/` (this file lives with it). All numbers measured live on
this machine (Hyprland 0.56.0, single eDP-1 1920x1200, grim + tesseract 5.5.3), plus a
~13-min real-usage event log (`capture.sqlite3`) collected during an actual session
(email game → Obsidian/terminal → YouTube tutorial) and a keepalive OCR run.

## 1. grim → tesseract latency & size (1920x1200)

| capture | grim | tesseract (full-res) | size |
|---|---|---|---|
| PNG l6 (default) | 94ms | ~4.3s | 626KiB |
| **JPEG q80** | 27ms | ~4.3s | 284KiB (real: avg 282KiB) |
| JPEG q70 | 29ms | — | 238KiB |
| JPEG q50 | 31ms | — | 190KiB |
| JPEG q30 | 33ms | — | 153KiB |

- **tesseract is the bottleneck: ~4.3s/frame sustained → ~0.23 frames/s max.** Capture
  events are cheap (grim 27ms); OCR must run in a worker queue, not the event loop.
- Half-scale OCR (1.4s) drops ~half the text (small UI unreadable); quarter-scale is
  useless (0 chars). Keep full-res for content.
- **Region capture wins**: grim `-g` on the active window's `at/size` → 209KiB vs 257KiB,
  cleaner OCR (status-bar/wallpaper noise gone), and only captures what the user is
  looking at (privacy). Recommend region, not full-screen.

## 2. Event burstiness & debounce

- A single focus/workspace change emits a burst of **6–8 events over ~200–400ms**
  (`activewindow`, `activewindowv2`, `workspace`, `workspacev2`, create/destroy ws…).
- **1.5s debounce → 1 capture per burst** (measured: bursts collapse to single fires).
- `grim`'s own capture emits `screencast>>0/1,monitor` events — must be excluded from the
  trigger filter or the loop self-triggers (verified: our filter excludes them).

## 3. The critical question: silent gaps — CONFIRMED, and partially solved by events

**Pure event-driven capture leaves long silent gaps.** In a ~13-min real session:

- **94% of the time had no window events** (gaps ≥30s); longest gap **5.7 min**;
  a single terminal window (herdr) was focused for **9.2 min straight** → 0 captures.
- A YouTube video played in Chrome: the **navigation** fired `windowtitlev2` with the full
  video title (event-visible), then **playback was silent** — no events until the next
  switch. So: YouTube/movie *starts* are caught; *duration* is a silent gap.
- `windowtitlev2` exists and fires on title changes → browser navigation / page changes /
  per-video YouTube titles are event-visible. This shrinks the gap problem a lot.
- **Music is fully invisible to socket2**: sidra's window title is static (`Sidra`), so no
  events per track. **MPRIS** (`playerctl --player=sidra metadata`, `--follow`) exposes
  artist/title/album → subscribe to MPRIS for track changes. (Current state: music paused;
  the MPRIS path is validated but not yet observed firing.)

**Keepalive is required.** A 1-min keepalive captured frames during the 5.7-min silent
stretch (279–286KiB, 3.7–4.6s OCR each) that pure event-driven would have missed entirely.

## 4. Window metadata at capture time (`hyprctl activewindow -j`)

`class, title, workspace{id,name}, monitor, fullscreen, pid, address, at{x,y}, size{w,h}, floating`.
All available in ~10ms; the socket event already carries class+title for activewindow.

## 5. Storage estimate (JPEG q80, ~282KiB/frame, 12h active day)

| design | frames/day | GB/month |
|---|---|---|
| event-driven, min-interval 60s (this session's burst rate) | ~140 | **~1.1** |
| event-driven, no throttle (this session, 30s) | ~350 | ~2.8 |
| keepalive 2 min | 360 | 2.9 |
| **keepalive 5 min** | 144 | **1.2** |
| keepalive 10 min | 72 | 0.6 |
| keepalive 15 min | 48 | 0.4 |
| keepalive 30 min | 24 | 0.2 |

OCR text ~1.5–3.5KB chars/frame → negligible vs images. Full-res OCR adds CPU, not bytes.

## 6. OCR text quality

Terminal text is legible ("Build & Deploy ML Churn model with FastAPI, MLFlow, Docker,
& AWS | Anas Riad | 11K subscribers | how you can clone a…"). Status bar / small UI text
garbles ("rmws% Qoomected 5% @s0%"). Region capture removes most noise. Usable for the
recap pipe.

## Recommended design (for the spec, pending user HITL)

- **Triggers**: `activewindow>>`, `openwindow>>`, `workspace>>`, `fullscreen>>`,
  `windowtitlev2>>` (title change, deduped) + **MPRIS track-change** (music) +
  **keepalive every N min** (safety net for static windows: movies, reading, terminal).
- **Debounce 1.5s**, **min-interval 10–30s**, OCR worker queue with drop-on-overflow.
- **Capture the active-window region** (`grim -g <at> <size>`), **JPEG q80**.
- Keepalive N is the user's storage-vs-coverage call: **5 min → 1.2 GiB/month** (recommended)
  or **10 min → 0.6 GiB/month**.
