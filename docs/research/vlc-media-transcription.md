---
# Ticket #32 — Local transcription of VLC media: subtitle tracks vs ASR

How can heimdall turn a VLC watch-session's watched range `[start, end]` into a transcript,
fully locally? Two candidate paths: (a) extract the file's **subtitle track** and slice the
range out, or (b) run **local ASR** on the range's audio. Everything below was verified on
this machine or cited from a primary source; nothing was benchmarked here.

## 0. Machine snapshot (verified live, relevant subset)

From `docs/research/fallback-engines-viability.md`, plus checks done for this ticket.

| item | value |
|---|---|
| CPU | Intel Core Ultra 9 185H, 16 threads, x86_64 |
| RAM | 30.8 GiB |
| GPU | Intel Arc (Meteor Lake-P) — **Vulkan-only, no CUDA** |
| ffmpeg/ffprobe | **n8.1.2** (built with `--enable-libass --enable-libdav1d`, Vulkan/OpenCL) |
| network | works (HTTPS 200 to raw.githubusercontent.com, docs.faster-whisper.com, alphacephei.com, archlinux.org) |
| arch package | `whisper-cpp 1.9.1-1` available in Extra/x86_64 (fetched 2026-08-03) |

## 1. Verdict at a glance

| path | verdict | notes |
|---|---|---|
| Subtitle track (embedded) | **DO THIS FIRST** | free, exact, zero compute; present on the MKV, absent on the 3 self-made MP4s |
| Subtitle track (external sidecar `.srt`) | works | ffprobe on the video **never sees sidecars** — must discover by filename convention and pass as an explicit 2nd `-i` |
| Local ASR (whisper.cpp / faster-whisper) | **viable fallback** | `small` model ≈ 0.13–0.16× realtime on a comparable 8-thread CPU → a 2 h watch range ≈ 16–20 min, well inside "nothing leaves the machine" |
| Local ASR (vosk) | not a fit | streaming-oriented, WER well above Whisper, no batch pipeline for a 1–2 h range |
| "ArchWiki lists whisper.cpp" (ticket claim) | **unverifiable** | no `wiki.archlinux.org/title/Whisper.cpp` page exists (404, no Wayback snapshot); the real primary source is the package page |

**Answer to the ticket's explicit question:** ASR does **not** need to be ruled out of scope —
the numbers say it is cheap enough (a 2 h range ≈ 16–20 min on the CPU with the `small` model,
or ≈ 8 min batched+int8). Recommendation: implement subtitle-first, with faster-whisper (CPU
int8) as the ASR fallback.

## 2. Subtitle-track extraction (subtitle-first path)

### 2.1 What is actually available on real files

All verified with `ffprobe -v error -show_entries stream=index,codec_type,codec_name:stream_tags=language,title -of csv=p=0`.

- `stuff/tg-rag-video/TG-RAG_Explained.mp4` (386.75 s): `0,h264,video` + `1,aac,audio` — **no subtitle stream**
- `stuff/manim-hnsw/final_voiced.mp4` (172.58 s): `0,h264,video` + `1,aac,audio` — **no subtitle stream**
- `stuff/codestreet-amex/video/final-narrated.mp4` (69.79 s): `0,h264,video` + `1,aac,audio` — **no subtitle stream**
- `~/Videos/...Project Hail Mary 2026 IMAX 1080p WEBRip...MoviesMod.Farm.mkv` (9396.09 s, format `matroska,webm`):
  - `0,h264,video` (1920×1080)
  - `1,aac,audio,hin` (2ch)
  - `2,aac,audio,eng` (6ch)
  - `3,subrip,subtitle,eng` (title `MoviesMod.Farm`) — clean dialogue
  - `4,subrip,subtitle,eng` (title `MoviesMod.Farm`) — SDH (`[thudding]`, `[Mary]` speaker tags)

So the realistic corpus splits: self-made videos have **no subtitles** (ASR is the only path
there); downloaded media often embeds an English subtitle track (extraction wins).

### 2.2 Detect a subtitle stream (per watch-session file)

```sh
ffprobe -v error -select_streams s -show_entries stream=index,codec_name,codec_type -of csv=p=0 "$FILE"
# → 3,subrip,subtitle / 4,subrip,subtitle   (MKV above)
# → (empty)                                  (the 3 MP4s)
```

Empty output ⇒ no embedded subtitle track ⇒ ASR fallback.

### 2.3 Slice the watched range `[start, end]` out of an embedded track

Verified recipe (start=5400 s, 30 s window):

```sh
ffmpeg -v error -ss 5400 -i "$FILE" -map 0:3 -t 30 -f srt -
# → 5 cues, timestamps relative to the slice (00:00:00,000 --> 00:00:03,276 ...)
```

**Quirk found (verified repeatedly):** `-to 5430` does **not** truncate embedded MKV subtitle
demux — it returned all 604 cues spanning 01:00:33→01:01:01. Use `-t <end-start>` as an *output*
option, not `-to`. For the daemon: `-ss "$start" -i "$FILE" -map 0:N -t "$((end - start))" -f srt -`
produces a local, range-relative SRT ready for the FTS5 index.

The full-track extract is equally simple and doubles as a test fixture:
`ffmpeg -v error -i "$FILE" -map 0:3 -c:s srt full.srt` → 7732 lines for the MKV.

### 2.4 External sidecar `.srt` files

Verified: a standalone `.srt` is a normal ffmpeg input (`codec_name=subrip`, `format_name=srt`)
and slices exactly like embedded tracks: `ffmpeg -v error -ss 120 -t 60 -i sub.srt -f srt -`.

Important implication for the daemon: **ffprobe on the video file alone never sees external
sidecar files** — there is no "classic matcher" to lean on. The daemon must discover sidecars
by filename convention (e.g. `<basename>.srt` next to `<basename>.mp4/mkv`) and pass them as a
separate `-i` input. The SRT muxer accepts only one subtitle stream per output (verified), so
embedded+sidecar combination is not needed here — pick embedded first, then sidecar.

## 3. Local ASR options (fallback path)

All three are CPU-capable and ship no data off the machine. Figures below are primary-source
claims; latency was not measured here.

### 3.1 whisper.cpp (ggml-org, stable v1.9.1)

Primary source: repo README (fetched 2026-08-03). Plain C/C++, no Python deps; CPU-only
inference is a first-class path (AVX intrinsics, F16/F32 mixed precision, integer
quantization); optional Vulkan (our iGPU is Vulkan-only if we ever want GPU). Zero memory
allocations at runtime; optional Silero VAD to skip non-speech. CLI needs 16-bit WAV input
(`ffmpeg -i in -ar 16000 -ac 1 -c:a pcm_s16le out.wav`).

Model size/memory table (README):

| model | disk | mem (runtime) |
|---|---|---|
| tiny | 75 MiB | ~273 MB |
| base | 142 MiB | ~388 MB |
| small | 466 MiB | ~852 MB |
| medium | 1.5 GiB | ~2.1 GB |
| large | 2.9 GiB | ~3.9 GB |

Availability: `whisper-cpp 1.9.1-1` in archlinux Extra (x86_64), "Port of OpenAI's Whisper
model in C/C++", replaces `whisper-cpp-rocm`/`whisper-cpp-vulkan`. The ticket's ArchWiki claim
could not be verified (no such wiki page exists); the package page is the citable source.

### 3.2 faster-whisper (SYSTRAN, CTranslate2)

Primary source: repo README (fetched 2026-08-03). Reimplements Whisper on CTranslate2; "up to
4 times faster than openai/whisper for the same accuracy while using less memory"; 8-bit
quantization on CPU supported; FFmpeg not needed (PyAV bundles it); segments carry start/end
timestamps, `word_timestamps=True` gives per-word timing, Silero VAD integrated.

CPU benchmark from the README (13 min audio, `small` model, beam=5, **8 threads, Intel Core
i7-12700K**):

| implementation | precision | time | RAM |
|---|---|---|---|
| openai/whisper | fp32 | 6m58s | 2335 MB |
| whisper.cpp | fp32 | 2m05s | 1049 MB |
| whisper.cpp (OpenVINO) | fp32 | 1m45s | 1642 MB |
| faster-whisper | fp32 | 2m37s | 2257 MB |
| faster-whisper `batch_size=8` | fp32 | 1m06s | 4230 MB |
| faster-whisper | int8 | 1m42s | 1477 MB |
| faster-whisper `batch_size=8` | int8 | **51s** | 3608 MB |

(GPU numbers, same README, RTX 3070 Ti, 13 min, Large-v2: faster-whisper int8 59s/2926 MB,
whisper.cpp fp16 1m05s/4127 MB — not applicable to this machine but shows both engines are
equivalent quality/perf when the hardware differs.)

### 3.3 vosk (Kaldi)

Primary source: alphacephei.com/vosk/models (fetched 2026-08-03). Streaming decoder, not a
batch transcriber; small models ~50 MB / ~300 MB runtime RAM, big models up to ~16 GB RAM.
English options: `vosk-model-small-en-us-0.15` (40M, WER 9.85 librispeech-clean),
`vosk-model-en-us-0.22` (1.8G, WER 5.69). WER sits well above Whisper `small`/`medium` for the
same cost, and there is no ready-made batch pipeline for a 1–2 h watched range → deprioritize.

### 3.4 Feasibility for a 1–2 h watch range (extrapolation)

Using the only primary CPU numbers available (8 threads, i7-12700K, `small` model, 13 min audio):

| engine | wall time per 1 h audio | per 2 h audio |
|---|---|---|
| whisper.cpp `small` fp32 | ~9.6 min | ~19 min |
| faster-whisper `small` int8 | ~7.9 min | ~16 min |
| faster-whisper `small` batch8 int8 | ~3.9 min | ~7.9 min |

Our CPU has 16 threads vs the 8 used in the benchmark, so real numbers should be equal or
better; treat these as upper bounds. Memory is a non-issue (`small` ≈ 0.85–1.5 GB runtime).
A VLC watch-session is usually well under the full file (often 20–60 min), so typical wall
time is 2–10 min per session.

## 4. Recommendation

1. **Subtitle-first (embedded track):** probe with `-select_streams s`; if present, slice the
   watched range with `-ss $start -i file -map 0:N -t $dur -f srt -` (not `-to`). Zero cost.
2. **Sidecar fallback:** discover `<basename>.srt` by convention, demux as separate `-i`.
3. **ASR fallback (no subtitles):** faster-whisper, `small` + int8 on CPU, transcribe only the
   audio of `[start, end]` (extract via ffmpeg → 16 kHz mono PCM). ~0.13× realtime ⇒ in scope.
   whisper.cpp (`whisper-cpp` from Extra) is the zero-dependency alternative if the Python
   wheel route is unwanted.
4. **Drop vosk** from the shortlist for this use case.
5. Correct the ticket's premise: cite the archlinux.org `whisper-cpp` package page, not ArchWiki.

## 5. Sources (all fetched 2026-08-03 unless noted)

- whisper.cpp README (stable v1.9.1) + models/README — features, size/memory table
- faster-whisper README — claims + CPU/GPU benchmark tables
- alphacephei.com/vosk/models — model sizes, WER table
- archlinux.org/packages/extra/x86_64/whisper-cpp — package facts (1.9.1-1)
- Matroska RFC 9559 (rfc-editor.org, `/tmp/rfc9559.txt`) — TimestampScale §5.1.2.9 (base
  nanoseconds; 1000000 = ms), BlockDuration §5.1.3.5.3 (subtitle breaks), timestamps in Track
  Ticks §11.1–11.2
- ffmpeg(1) option docs (n8.1.2) — `-ss`/`-t`/`-to` semantics (verified: `-to` ≠ `-t` here)
- WebVTT CRD 2026-05-20 (W3C) — external text-track resource semantics
- Local verification: ffprobe/ffmpeg n8.1.2 on 4 real media files (outputs in §2)
