"""Lazy on-demand ASR for subtitle-less watch sessions (v2 #40).

A closed session on a local file with no caption transcript can be made
searchable on demand: `GET /sessions/{id}/transcript` extracts the *watched*
video-time sub-ranges to 16 kHz mono PCM with ffmpeg, runs faster-whisper
(`small`, int8, CPU) lazily — never at capture time — and stores the result on
the session row with `transcript_source='asr'`.

faster-whisper is imported lazily and the ctranslate2 model loads once on first
use (it downloads ~460 MB from HuggingFace on a fresh machine); load and each
transcribe run under one lock because ctranslate2 models are not thread-safe.
Everything here is fail-soft: the job records the error and the session stays
title-only until retried.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
import urllib.parse
from typing import Optional

log = logging.getLogger("heimdall.asr")

AUDIO_RATE = 16000


def local_media_path(source: Optional[str]) -> Optional[str]:
    """Filesystem path of a session's media_source, else None.

    VLC exposes `file:///mnt/movies/Inception.mkv`; an http YouTube URL or a
    bare title has no local audio to extract, so ASR cannot serve it.
    """
    if not source or not source.startswith("file://"):
        return None
    return urllib.parse.unquote(source[len("file://"):])


def extract_ranges_pcm(media_path: str, ranges_us: list[list[int]], *,
                       ffmpeg: Optional[str] = None,
                       run=None) -> Optional[bytes]:
    """The watched sub-ranges of a local file as 16 kHz mono float32 PCM.

    Each watched range is extracted with ffmpeg (`-ss` input seek, `-t` exact
    duration, raw f32le on stdout) and concatenated, so a seek-skipped gap
    contributes no audio at all. Returns None on any failure — missing file,
    no ffmpeg, corrupt media.
    """
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    run = run or subprocess.run
    chunks: list[bytes] = []
    for start_us, end_us in ranges_us:
        if end_us <= start_us:
            continue
        start_s = start_us / 1_000_000
        dur_s = (end_us - start_us) / 1_000_000
        cmd = [ffmpeg, "-v", "error", "-ss", f"{start_s:.3f}", "-i", media_path,
               "-t", f"{dur_s:.3f}", "-vn", "-ac", "1", "-ar", str(AUDIO_RATE),
               "-f", "f32le", "-"]
        try:
            proc = run(cmd, capture_output=True)
        except OSError:
            return None
        if proc.returncode != 0:
            log.warning("ffmpeg extract failed for %s: %s", media_path,
                        proc.stderr.decode(errors="replace")[-300:])
            return None
        chunks.append(proc.stdout)
    if not chunks:
        return None
    return b"".join(chunks)


class AsrEngine:
    """Lazily-loaded faster-whisper model; load + transcribe are serialized."""

    def __init__(self, *, model_size: str = "small", device: str = "cpu",
                 compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._lock = threading.Lock()

    def transcribe(self, pcm: bytes) -> Optional[str]:
        """Whisper transcript of raw 16 kHz mono float32 PCM, or None."""
        with self._lock:
            model = self._load()
            if model is None:
                return None
            import numpy as np

            audio = np.frombuffer(pcm, dtype=np.float32)
            try:
                segments, _ = model.transcribe(audio, sampling_rate=AUDIO_RATE)
                text = "\n".join(s.text.strip() for s in segments).strip()
            except Exception as exc:  # noqa: BLE001
                log.warning("asr transcription failed: %s", exc)
                return None
            return text or None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            log.warning("faster-whisper not installed; ASR unavailable")
            return None
        try:
            self._model = WhisperModel(self.model_size, device=self.device,
                                       compute_type=self.compute_type)
        except Exception as exc:  # noqa: BLE001
            log.warning("asr model load failed: %s", exc)
            return None
        return self._model


class AsrManager:
    """Orchestrates the lazy ASR job behind `GET /sessions/{id}/transcript`.

    `request()` is the single seam the endpoint calls: it either returns the
    stored transcript (cached — a repeat call never re-runs), reports the
    in-flight job, or spawns the worker thread and reports it queued. A failed
    job is retried on the next request; a finished job is cleared from the
    registry so the DB row is the single source of truth.
    """

    def __init__(self, config, db):
        self.config = config
        self.db = db
        self.engine = AsrEngine(
            model_size=config.asr.model,
            device=config.asr.device,
            compute_type=config.asr.compute_type,
        )
        self._lock = threading.Lock()
        self._jobs: dict[int, dict] = {}

    def pending(self) -> dict:
        """Snapshot of the job registry for `heimdall status` (#42).

        Queued and running jobs are the "pending" work; a failed job is kept
        until its next request retries it, so it shows up too.
        """
        with self._lock:
            items = [
                {"session_id": sid, "status": job["status"],
                 "started_at": job["started_at"], "error": job.get("error")}
                for sid, job in sorted(self._jobs.items())
            ]
        return {
            "queued": sum(1 for it in items if it["status"] == "queued"),
            "running": sum(1 for it in items if it["status"] == "running"),
            "failed": sum(1 for it in items if it["status"] == "failed"),
            "items": items,
        }

    def request(self, session_id: int) -> tuple[int, dict]:
        """Resolve one `/sessions/{id}/transcript` call into (status, body)."""
        session = self.db.get_watch_session(session_id)
        if session is None:
            return 404, {"detail": f"session {session_id} not found"}
        if session["live"]:
            return 409, {"detail": "session is still in progress"}
        if session.get("transcript"):
            return 200, {
                "session_id": session_id,
                "transcript": session["transcript"],
                "transcript_source": session.get("transcript_source"),
                "cues_json": session.get("cues_json"),
            }
        path = local_media_path(session.get("media_source"))
        if path is None:
            return 422, {"detail": "session has no local media file to transcribe"}
        with self._lock:
            job = self._jobs.get(session_id)
            if job is not None and job["status"] != "failed":
                return 202, {"session_id": session_id, "job": dict(job)}
            job = {
                "status": "queued",
                "started_at": int(time.time() * 1000),
                "error": None,
            }
            self._jobs[session_id] = job
            body = {"session_id": session_id, "job": dict(job)}
        threading.Thread(
            target=self._run, args=(session_id, path, session["ranges"]),
            name=f"asr-{session_id}", daemon=True,
        ).start()
        return 202, body

    def _run(self, session_id: int, path: str,
             ranges: list[list[int]]) -> None:
        self._set(session_id, "running")
        try:
            pcm = extract_ranges_pcm(path, ranges)
            if not pcm:
                raise RuntimeError("ffmpeg audio extraction failed")
            text = self.engine.transcribe(pcm)
            if not text:
                raise RuntimeError("ASR produced no text")
            self.db.update_session_transcript(
                session_id, cues_json=None, transcript=text,
                transcript_source="asr",
            )
            self._done(session_id)
        except Exception as exc:  # noqa: BLE001 — job failure is recorded, not raised
            log.warning("asr job %s failed: %s", session_id, exc)
            self._set(session_id, "failed", error=str(exc))

    def _set(self, session_id: int, status: str,
             error: Optional[str] = None) -> None:
        with self._lock:
            job = self._jobs.get(session_id)
            if job is None:
                return
            job["status"] = status
            if error is not None:
                job["error"] = error

    def _done(self, session_id: int) -> None:
        with self._lock:
            self._jobs.pop(session_id, None)
