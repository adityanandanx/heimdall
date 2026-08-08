# Heimdall — "Screen Memory" (video script)

- **Format:** 16:9, ~4:00 target (VO ≈ 560 words)
- **Audience:** developers / Linux + Hyprland-curious builders
- **Spine:** the real git lifecycle — 93 commits, 2026-08-02 → 2026-08-06
- **Concept:** *The Build Journal* — the commit graph is the story; each act lands on real artifacts from the repo
- **Assets available:** OCR bench frames (`prototypes/screen-content/bench/frames/*.jpg`), day-browser prototype, desktop Tauri UI, `architecture.mmd`, real commit hashes

```
ACT STRUCTURE
Act 1  The Hook        (0:00)  git log, 93 commits, the question
Act 2  The Problem     (0:20)  screens you'll never see again
Act 3  Day One         (0:50)  commit fdf5f89 — the plan diagram
Act 4  Capture         (1:15)  a11y tree > OCR, phash dedupe
Act 5  Watch Sessions  (1:50)  MPRIS, CDP → MV3 extension, captions, ASR
Act 6  Search          (2:25)  FTS5, merged search, facets, query language
Act 7  The Scribe      (2:55)  daily recap + time breakdown pipes, local Gemma
Act 8  The Window      (3:25)  prototypes → Tauri v2 desktop client
Act 9  The Close       (3:45)  nothing leaves the machine
```

---

## ACT 1 — THE HOOK (0:00–0:20)

**VISUAL**
Dark canvas (`#0c0f14`, One Dark vibe). A terminal window opens; text types in:

```
$ git log --oneline | wc -l
93
$ git log --since "5 days ago" --author="Aditya"
fdf5f89 Initial project plan and architecture for Heimdall
…
```

The lines blur into a glowing question card:

> “If I asked you to find the exact moment you saw that bug yesterday… could you?”

**VO**
> “Five days. Ninety-three commits. One idea: your screen, remembered.
> This is Heimdall — a local, screen-only memory system for Hyprland.
> And this is the story of how a blank repo became a machine that remembers everything you’ve seen.”

**TITLE CARD: HEIMDALL — SCREEN MEMORY**

---

## ACT 2 — THE PROBLEM (0:20–0:45)

**VISUAL:** A montage of a real workday — split frames: code editor, browser with a dozen tabs, a terminal wall, VLC paused, a PDF open. Doubles as the real `frames/` gallery (bench frames). Overlay stickers as a “things you saw today” checklist being struck through: `that buggy line` ✗ · `the discount code` ✗ · `the tutorial timestamp` ✗. Last frame: empty search box, cursor blinks: “where did I see —”.

**VO**
> Every day your eyes cover hundreds of things you’ll never see again. A bug in a commit diff. A number in a spec. That one minute in a tutorial. Not because you failed to save it — because saving wasn’t an option. Nothing was written down. This assumes the screen itself should keep a diary — automatically, privately, completely locally.

---

## ACT 3 — DAY ONE (0:45–1:15)

**VISUAL:** The actual `architecture.mmd` renders as an animated flowchart, box by box assembling left→right: Hyprland socket → Capture Daemon → SQLite + FTS5 → FastAPI `127.0.0.1:3030` → Pipes → llama-server. A permission stamp: `fdf5f89 · 2026-08-02 · PLAN`. Under a badge: `every arch choice survived to v1`.

**VO**
> “August 2nd — the first commit. Not code — a plan.
> One flowchart that would survive almost everything: Hyprland’s event socket triggers a capture daemon; grim screenshots just the active window; the frame is read; SQLite + FTS5 store it; a FastAPI server on localhost serves it; and every night at 11:00, a local LLM summarizes the day.
> What was written that morning still stands — and nothing ever leaves the machine.”

---

## ACT 4 — CAPTURE (1:15–1:50)

**VISUAL:** A filmstrip of real frames (kitty, chrome, code windows). One frame zooms; a scanline sweeps the window; OCR-highlight overlay shows copyable text. Then a compare card: `tesseract OCR ~4.3 s/frame` vs `a11y tree: near-instant, exact text`, and the phash check: frame A vs frame B, `phash 0.87 → DROP`.

**VO**
> Then the actual seeing. No recording streams — that would eat disks, and pie: Heimdall captures moments. When you switch windows, the daemon listens — `activewindow`, `windowtitle` — debounced, and grabs only the active-window region as a ~280 KB JPEG.
> The smartest call came early, heuristics gave way after the first real tests: **the accessibility tree**. Windows already contain their own clean text — AT-SPI exposes it. So Heimdall reads the a11y tree directly — fast and exact — and keeps OCR (RapidOCR, later accelerated) for apps without one. A perceptual hash keeps duplicate frames out: you store *changes*, not noise.

---

## ACT 5 — WATCH SESSIONS (1:50–2:25)

**VISUAL:** MPRIS card with `playerctl status` rows appearing; playing vs paused domains painted as colored bars on a timeline. A Chromium flow: `CDP — shadow DOM` morphs into `MV3 native-messaging extension` badge. A watch-session block slides on: `YouTube — “the whole story” — 18:24 → 20:52, transcript ✓`. For VLC: `no captions → ffmpeg → faster-whisper (ASR) ← lazy`.

**VO**
> Frames are one surface. What about what you *watched*? Every music and video player on Linux speaks MPRIS — so Heimdall tracks the track and the session: what played, when, and the exact watched range. That becomes a first-class memory.
> In browsers, it harder: no player metadata. A Chromium extension — native messaging, MV3 — resolves the real page URL, this isn’t a screenshot of the screen; it’s an address: *you watched this video, this range, and here’s what was said*. Captions come from yt-dlp when they exist; when they don’t, audio is extracted and transcribed with a WHISPER ASR — lazily, only onto the machine that watched it.

---

## ACT 6 — SEARCH (2:25–2:55)

**VISUAL:** Search bar typing `phash` — results slide in with scores `0.92 · class:kitty · window:3`, the matching frame highlight-swayed with a dot. Merge two hit types side-by-side: a *frame* hit (thumbnail + snippet) and a *session* hit (title + range). Filter chips fill: `app: chromium`, `player: vlc`, `ws / monitor / fullscreen`. Query-language demo with syntax glow: `phash site:kitty date:yesterday`.

**VO**
> And all of it is **searchable** — FTS5. Frames, app text, session transcripts — one index. Filter by app, by player, by workspace or fullscreen. A frame hit is a screenshot with a snippet; a session hit is a title with a watched range.
> There’s a mini query language with syntax glow, facets, live suggestions that jump straight to the timeline — every result becomes *a moment you can time-travel to*.

---

## ACT 7 — THE SCRIBE (2:55–3:25)

**VISUAL:** scheduler ticks: `day_recap @ 23:00` and `time_breakdown @ 23:05`. A Markdown file opens — `output/day-recap-YYYY-MM-DD.md` with front matter (date+range+frame_count) — and a bar chart renders from the breakdown: `code 4h10m · watching 1h35m · music 40m`. A faint trace line pings in the corner: `langfuse · trace`.

**VO**
> Collecting every frame is only a memory — a *story*. So every night at 11, two pipes run.
> The AFL daily recap: an LLM on local llama-server — Gemma, Qt, Vulkan — reads the day’s frames and text and writes Markdown: what you did, what you built, what you watched, even suggesting the rewatch.
> A second pipe does the math: a time breakdown merged over N days, minutes per category.
> Every pipe can be traced — observability on the same box, all local, still.

---

## ACT 8 — THE WINDOW (3:25–3:45)

**VISUAL:** Day-browser prototype fades into a Tauri v2 desktop client (real desktop UI): Day surface with filmstrip + media lanes, hover-preview, then Search / Sessions / Status surfaces left, **One Dark** palette chips — `#0c0f14 · #5b8cff · #3ecf8e` — top right. App screen: settings surface toggling servers.

**VO**
> All that power deserved a proper window. After web prototypes — a scrubber, a day-browser — the UI landed as a native Tauri v2 client: a beautiful dark timeline of the day, filmstrip of every frame, parallel media lanes for watch sessions, live following, hover previews.
> Day. Search. Sessions. Status. Settings — every surface against the same local API, `127.0.0.1:3030`, loopback-only.

---

## ACT 9 — THE CLOSE (3:45–4:00)

**VISUAL:** slow pull-back to the Act 3 diagram, now fully lit; every part lights, from capture to pipes, then fades to black with the end card:
```
heimdall — screen memory
Nothing leaves the machine.
github.com/<your-org>/heimdall
```

**VO**
> So the next time you lose a moment, Heimdall can find it. Local, private, exact, searchable — and the whole build, from a single plan commit to a 93-commit machine that reads, transcribes, summarizes, and re-members everything you see.
> Your screen keeps a diary. Nothing ever leaves your machine.
>
> **heimdall — from a blank repo to a memory, in five days.**

---

## PRODUCTION NOTES

- **Assets (in-repo):** use `prototypes/screen-content/bench/frames/*.jpg` for Act 2 + Act 4; day-browser `prototypes/day-browser/index.html` for Act 8 fades; capture `desktop/` screenshots (real) for Act 8; `architecture.mmd` animated for Acts 3 + 9.
- **Hash sources:** commit lines quoted from real log (verify `fdf5f89`, `f7799b`); folds to “93 commits, 5 days”.
- **Music:** ambient dark tech beat, no bass drop; refrains under VO.
- **Pace notes:** VO ≈ 140 words/min; each act ≤ 30 s; Act 5 (watch sessions) is the longest — trim to 30 max if the run goes long.
- **Legal/privacy:** never reveal real user data in frames; use the bench corpus (already synthetic) or clip faces/non-relevant windows.