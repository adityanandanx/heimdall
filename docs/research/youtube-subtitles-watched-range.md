# Ticket #31 — YouTube subtitle retrieval for watched-range transcription

Research (AFK) for the local-only screen-content pipeline: a watch-session capture records a
YouTube URL + watched range `[start, end]` (via MPRIS/CDP). Question: can we retrieve the
video's transcription and slice it to the watched range, reliably and **local-only** (no cloud
transcription; caption download over HTTPS is fine)?

Everything below was **verified live on this machine** (2026-08-03, yt-dlp `2026.07.04`
installed into a scratch venv at `/tmp/opencode/ytdlp-venv`) or is cited from a primary source
(yt-dlp README, yt-dlp source in the installed wheel, yt-dlp wiki, youtube-dl README, YouTube
Data API reference). Source line numbers refer to the installed `2026.07.04` wheel unless stated.

## Verdict at a glance

**YES — viable.** The caption track is an **HTTPS GET of a signed `timedtext` URL** that
YouTube itself puts in the player response; yt-dlp extracts it and downloads it. No cloud
transcription, no video download, tiny payloads (55–500 KB). Verified 5/5 sampled
uploads (4 from the user's browsing history + a music-video control) had captions
retrievable this way.

- **Recommended fetch path (programmatic):** `yt-dlp -J` once → take
  `automatic_captions[<lang>][*].url` (the signed `api/timedtext` URL) → HTTPS GET it with
  `fmt=json3` (or `srv3`). Do **not** hand-build a `timedtext` URL — unsigned URLs return HTTP
  200 with an **empty body** (verified), and the legacy `get_video_info` endpoint is HTTP 410
  Gone (verified). The signature/`expire` come from the player response; yt-dlp's extractor is
  the robust source for them.
- **Manual > auto, but auto is the safety net.** Prefer a manual track when present
  (`--write-subs --write-auto-subs` lets manual win), otherwise auto (ASR) captions — present
  for every one of our 5 sampled videos (incl. a live-stream VOD), but quality is ASR-grade and
  a small share of videos have neither.
- **Slicing:** keep cues with `end > start` and `start < end`; clamp the first kept cue's start
  and the last kept cue's end to the watched boundaries; prefer **json3/srv3** (structured,
  ms-precision, no inline markup) over vtt (auto vtt carries inline `<00:00:00.000>` tags and
  `<c>` markup that must be stripped for clean text). Slice lives as a **column** (sliced
  cues JSON + a denormalized plain-text column for FTS5), mirroring the existing `frames`/
  `frames_fts` pattern; raw caption file cached on disk (signed URL expires in hours, so
  cache the *content*, not the URL).
- **Flags that could make it non-viable per-video:** age-gated (needs authenticated cookies),
  region-blocked, removed/unavailable, still-live streams (captions arrive only after
  processing), videos with no caption track at all. All are clean, detectable failures — the
  pipeline should degrade to OCR for those.

## 1. Machine snapshot (verified)

| item | value |
|---|---|
| yt-dlp | `2026.07.04` installed via `pip` into a scratch venv at `/tmp/opencode/ytdlp-venv` (system Python 3.14.6) — install succeeded over the network |
| network | HTTPS works: `pypi.org` (pip install succeeded), `youtube.com`, `github.com`, `developers.google.com` all 200 |
| ffmpeg | `/usr/bin/ffmpeg` present (not needed — captions are not media; ffmpeg is only used if you remux) |
| impersonation deps | **not installed** (no `curl_cffi`); yt-dlp warned *"extractor specified to use impersonation… no impersonate target is available"* but **still downloaded every caption successfully** |
| cookies | none used for the 6 working fetches (no `--cookies`); age-gated fetch failed without them |

## 2. Mechanism: `--write-subs` / `--write-auto-subs` is a pure HTTPS fetch, no transcription

Confirmed in the yt-dlp source:

- Subtitle *selection* happens in `YoutubeDL.process_subtitles`
  (`yt_dlp/YoutubeDL.py:3160-3218`): requested langs are matched against the extractor's
  `subtitles` (manual) and `automatic_captions` dicts; when a lang exists in both, **manual
  wins** (`automatic_captions` entries are only added `if lang not in available_subs`,
  line 3168).
- Subtitle *writing* is `YoutubeDL._write_subtitles` (`YoutubeDL.py:4450-4504`): it calls
  `self.dl(sub_filename, sub_copy, subtitle=True)` — the ordinary **HTTP downloader over
  HTTPS**. No audio, no ASR, no cloud. The subtitle dict even carries `'impersonate': True`
  (extractor `youtube/_video.py:4204`) but that's only TLS-fingerprint impersonation for
  anti-bot, not transcription.
- Verbose run proof (`--verbose --write-auto-subs --sub-langs en --sub-format json3`):

  ```
  [debug] Invoking http downloader on "https://www.youtube.com/api/timedtext?v=5N-okeDdIuI&ei=...&caps=asr&...&expire=1785763671&...&signature=BFCF...&key=yt8&kind=asr&lang=en&variant=gemini&fmt=json3"
  ```
  → one HTTPS GET, then the file lands. No media is touched when `--skip-download` is used.

README (primary source, fetched 2026-08-03, `README.md:891-909`): `--write-subs` "Write
subtitle file", `--write-auto-subs` "Write automatically generated subtitle file",
`--sub-format FORMAT` "accepts formats preference separated by `/`", `--sub-langs` accepts
regex / `all`, and `README.md:2327`: *"Live chats (if available) are considered as subtitles.
Use `--sub-langs all,-live_chat` to download all subtitles except live chat"* — so a live VOD's
`live_chat` pseudo-track must be filtered out (it appeared in our `-J` as a "manual" entry).

### Output formats (verified against live videos)

Every language in `-J` ships all of: `json3, srv1, srv2, srv3, ttml, srt, vtt` (the extractor
builds all seven from one signed base URL, `youtube/_video.py:4194-4206`, appending `fmt`).
`--sub-format vtt/srv3` selects vtt first, falls back to srv3.

### Which classes fail — verified + source-cited

| class | behavior (verified live) | recoverable? |
|---|---|---|
| **age-gated** (`age_limit: 18`) | `ERROR: [youtube] HtVdAasjOgU: Sign in to confirm your age… Use --cookies-from-browser or --cookies` (tested `HtVdAasjOgU`, `Tq92D6wQ1mg`, both from yt-dlp's own test suite `youtube/_video.py:307,374`). Extraction fails outright unauthenticated. | Only with logged-in cookies. `--cookies-from-browser chrome` on this box still failed the age-gate (session not authed / keyring) — treat as "needs explicit cookie setup". |
| **removed / invalid id** | `ERROR: [youtube] AAAAAAAAAAA: Video unavailable` (tested). | No — gone. Detect from the error / absent `-J`. |
| **region-blocked** | No live case tested; yt-dlp surfaces `availability` (values incl. `public`, `unlisted`, `needs_auth` — `youtube/_video.py` test suite lines 183–1317) and errors on blocked playback. `-J`'s `availability` field is the cheap classifier. | Proxy/geo only; out of scope. |
| **still-live stream** | `ERROR: [youtube] 21X5lGlDOfg: This live stream recording is not available.` (tested two currently-live IDs). | Wait for VOD processing. **Archived live VODs are fine** — `251hsWgoTPM` (a completed live) had full auto captions. |
| **no caption track at all** | Rare; `--list-subs`/`-J` show empty dicts. | OCR fallback only. |
| **Made-for-kids / music** | Auto captions still present (rickroll `dQw4w9WgXcQ`: auto count 157, plus 5 manual langs). `android_vr` client can't serve M-for-K but `web_safari` can — yt-dlp iterates clients. | Fine. |

## 3. Robust path to the caption track: `-J` metadata vs the timedtext API directly

**Use `yt-dlp -J` (its extractor). The "direct" timedtext API is a trap.** Verified live:

| attempt | result |
|---|---|
| A) bare `api/timedtext?v=…&lang=en&fmt=json3` | **HTTP 200, empty body** |
| B) `…&kind=asr&key=yt8&caps=asr` | **HTTP 200, empty body** |
| C) legacy `…&type=list` | **HTTP 200, empty body** |
| D) `get_video_info?video_id=…` | **HTTP 410 Gone** |
| E) signed URL from `yt-dlp -J` (`…&signature=…&key=yt8&expire=…`) | **HTTP 200, real json3** |

Why: the working URL carries `signature`, `expire`, `sparams` (and on some tracks a `pot`
token) minted by YouTube inside the **player response**. The extractor reads them from
`playerCaptionsTracklistRenderer.captionTracks[].baseUrl` (`youtube/_video.py:4227-4315`) and
just appends `fmt`/`xosf`/`tlang`/`pot`. There is no stable unsigned caption endpoint anymore.

Two robustness notes from the primary source:

- **PO-token gating on `web` client.** YouTube is rolling out PO tokens for subtitle requests
  on `web` (yt-dlp wiki *PO Token Guide*, fetched 2026-08-03: *"Currently, only GVS and Subs
  require PO Tokens for some clients… `web`: Subs, GVS"*; `web_safari`/`android_vr`/`tv` are
  exempt for Subs). yt-dlp handles this transparently: it detects the requirement
  (`youtube/_video.py:4251-4268`) and retries the same tracks via clients that don't need a
  Subs PO token, only warning `"There are missing subtitles languages because a PO token was
  not provided"` when *all* clients fail. In our runs this fallback worked with **zero
  configuration**.
- **Signed URLs expire.** `expire` was set ~7 h after the player response was minted
  (observed `expire=1785763445` = 13:24 UTC vs ~06:24 UTC generation, verified). Fine for a
  same-day pipeline; the pipeline must cache caption *content*, not URLs.

## 4. Manual vs auto captions — what breaks for typical user videos

Verified on `5N-okeDdIuI` (L8 Principal's Agentic Dev Environment From Scratch), which has
**both** a manual `en` and auto `en`:

| track | cues | span | chars | notes |
|---|---|---|---|---|
| manual `en` | **391** | 0–2671 s | ~44 K | sentence-level cues (~6.8 s avg), curated text |
| auto `en` | **2179** | 0–2671 s | ~235 K incl. markup | line-level ASR cues (~1 s avg), ms inline timestamps |

- Auto captions are **ASR-generated** (`kind=asr`, `variant=gemini` in the URL — i.e. YouTube's
  current ASR engine). Quality is generally good for speech-heavy content but includes
  mis-hearings, `[applause]`-style annotations and, on long files, small timing drift.
- The `-J` list of ~157 auto "languages" is mostly **translation targets** (`tlang` param —
  machine-translated ASR); the genuine speech track is the `<lang>-orig` entry
  (`youtube/_video.py:4294-4315`, verified: `en-orig` == `en` URL for English videos). For a
  non-English video pick the track matching its audio language; for English, `en`.
- Failure mode for typical user videos: most uploads have **auto captions** (5/5 of ours),
  many lack **manual** ones; some niche videos have neither. The robust recipe is
  `--write-subs --write-auto-subs --sub-langs <lang>` and let manual take precedence; if no
  track exists, `-J`'s `automatic_captions`/`subtitles` dicts are empty → OCR fallback.

## 5. Caption timestamp precision — fine for `[1519 s, 2100 s]`

| format | granularity | verified |
|---|---|---|
| `vtt` | ms timestamps on every cue (`00:00:00.654 --> 00:00:03.830`) | 1281 cues over 1251 s on `qfEzUnZlMIo`; min inter-cue start delta **10 ms** |
| `srv3` (XML) | `<p t="654" d="2020">` ms + per-segment `<s t="…">` ms offsets | shown raw |
| `json3` (JSON) | events with `tStartMs` (ms) + `dDurationMs` + per-seg `tOffsetMs`; **10 ms** min step | 1281 events, 4363 segs on `qfEzUnZlMIo` |
| `srt`/`ttml` | ms | via same signed URL (`fmt` param) |

Subtitle timing is aligned to the video timeline; a slice to `[1519 s, 2100 s]` lands on the
correct content (demo below). Precision is not the constraint — **ASR drift** on long files and
**wall-clock→video-time alignment** from the capture are the real risks (see §7).

## 6. Watched-range slicing — approach + where the slice lives

Demo on `251hsWgoTPM` (4 480 s live VOD), range `[1519 s, 2100 s]`:

```
total cues in full track: 3537  (span 1.240 – 4477.440 s)
watched range: [1519.0 s, 2100.0 s]
cues overlapping range: 445        → 3312 words of clean-ish transcript
first kept cue: 00:25:19.000 --> 00:25:21.310
last  kept cue: 00:34:58.760 --> 00:35:00.000   (end clamped to boundary)
```

Approach (matches the pipeline's existing `frames_in_range` half-open `[start, end)` idiom,
`src/heimdall/db.py:169-186`):

1. **Fetch once per video**, not per slice: `yt-dlp -J` → pick track → HTTPS GET `fmt=json3`
   (structured; avoids vtt's inline `<00:00:00.000><c>…` karaoke markup that must be
   regex-stripped for clean text).
2. **Keep** cues with `end > start && cue_start < watched_end` (a cue straddling either
   boundary is still speech the user heard — keep it, don't drop it).
3. **Clamp** the first kept cue's start and the last kept cue's end to the watched boundaries
   (demo above: `00:34:58.760 --> 00:35:00.000`). Mid-range cues are untouched.
4. **Emit** (a) the sliced cues (JSON) with timestamps intact and (b) a denormalized plain-text
   column fed to FTS5 — mirrors the `frames`/`frames_fts` pattern already in the schema
   (`db.py:47-68`), so search over transcripts "just works" with the existing `porter unicode61`
   tokenizer. Optionally keep the full-track caption file on disk next to the DB (like
   `image_path`) to re-slice without a re-fetch.

**Where the slice lives:** a column (sliced-cues JSON + `plain_text`), not a file — it is
derived data of the watch session, sized ~KBs, and FTS-indexing a file requires the whole
external-content dance already solved for `frames`. The raw caption file (55–500 KB) can live on
disk under the data dir for re-slicing.

## 7. Flags that could make watched-range transcription non-viable

1. **Wall-clock vs video-time alignment.** The watch session records wall timestamps; the slice
   only means anything if the capture also records **video-time seconds** (MPRIS `position` /
   CDP `player.getCurrentTime`). If the current capture only has wall times, no caption slice
   can be aligned. Verify at prototype time.
2. **Age-gated / auth-gated videos.** Unauthenticated `-J` hard-fails. The user's own Chrome
   session can usually unlock these, but cookie export from Chrome on Linux needs a decryptable
   keyring; plan for `--cookies-from-browser chrome` being flaky headless.
3. **ASR drift on long VODs.** Auto-caption timing can drift over hours of content; a cue
   sliced at a precise boundary may be a word or two off. Manual tracks are safer when present.
4. **PO-token / impersonation escalation.** Subtitle fetches worked with zero config today, but
   the wiki documents rolling enforcement; if `web` Subs enforcement widens, add a PO-token
   provider plugin or install `curl_cffi` (impersonation) — one-time, still local-only.
5. **No-track videos.** A minority of uploads have no captions at all (or non-speech audio);
   detect via empty dicts and fall back to OCR frames (existing pipeline).

## 8. Cost / feasibility

- **Payloads:** caption files 55–500 KB per video (verified). `-J` is ~1 small API call; total
  per watched video ≈ tens of KB to ~0.5 MB. No quota (unlike the Data API), no media download,
  no GPU, no local ASR model. Cost ≈ one HTTP GET per watched video.
- **Official YouTube Data API is NOT a substitute**: `captions.list` costs **50 quota units**
  and needs authorization; `captions.download` costs **200 units** and *"requires the user to
  have permission to edit the video"* (developer docs, fetched 2026-08-03) — i.e. it is only for
  caption *owners*, useless for arbitrary watched videos. The `timedtext` route is the only
  general path.

## 9. Primary sources

- yt-dlp README (`--write-subs`/`--write-auto-subs`/`--sub-format`/`--sub-langs`, live-chat
  note), fetched 2026-08-03 — https://github.com/yt-dlp/yt-dlp/blob/master/README.md
- yt-dlp source, installed wheel `2026.07.04`: `yt_dlp/YoutubeDL.py:3160-3218,4450-4504`;
  `yt_dlp/extractor/youtube/_video.py:4190-4329` (captionTracks→signed URL→fmt/xosf/tlang/pot,
  `kind=asr`, `en-orig`, POT skip logic); age-gated tests at `_video.py:307,374`
- yt-dlp wiki *PO Token Guide* (Subs enforcement, `web` client, provider plugins), fetched
  2026-08-03 — https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide
- youtube-dl README (`--sub-format`), fetched 2026-08-03 — https://github.com/ytdl-org/youtube-dl
- YouTube Data API `captions.list` (quota 50, auth) and `captions.download` (quota 200, owner
  permission), fetched 2026-08-03 — https://developers.google.com/youtube/v3/docs/captions

## 10. Verification runs (all live, 2026-08-03, /tmp/opencode)

| video | result |
|---|---|
| `251hsWgoTPM` (Matt Pocock live VOD, 4 480 s) | `-J` OK; auto `en` vtt 514 KB, 3537 cues; slice `[1519,2100]` → 445 cues / 3312 words |
| `qfEzUnZlMIo` (Handmade Network, 1 251 s) | auto `en` vtt 191 KB / 1281 cues; json3 327 KB / 1281 events; srv3 XML ms-precision |
| `B6NVvtIz9_Q` (Samay Raina, 3 233 s) | auto captions present (157 langs incl. `en`); no manual |
| `5N-okeDdIuI` (Kun Chen, 2 671 s) | **manual + auto `en`**: manual 391 cues vs auto 2179 cues |
| `dQw4w9WgXcQ` (rickroll) | auto 157 langs + 5 manual langs (music videos often have manual) |
| `HtVdAasjOgU`, `Tq92D6wQ1mg` (age-gated) | **fail** unauthenticated (`Sign in to confirm your age`) |
| `21X5lGlDOfg`, `jfKfPfyJRdk` (currently live) | **fail** (`This live stream recording is not available.`) |
| `AAAAAAAAAAA` (invalid id) | **fail** (`Video unavailable`) |
| unsigned `timedtext` URLs (3 variants) | HTTP 200 **empty body**; `get_video_info` HTTP 410 |

Raw artifacts kept under `/tmp/opencode/` (`caps/*.vtt|srv3|json3`, `v*.json`, `slice_demo.py`).
