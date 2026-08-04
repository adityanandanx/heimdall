"""Lazy on-demand ASR (v2 #40): ffmpeg range extraction to 16 kHz mono PCM,
the local-media gate, and the AsrManager job flow behind the transcript
endpoint — cached results never re-run, failures are recorded and retried."""

from __future__ import annotations

import math
import shutil
import struct
import time
import wave

import pytest

from heimdall.capture.asr import AsrEngine, AsrManager, extract_ranges_pcm, local_media_path
from heimdall.config import Config


# ---- local-media gate ----

def test_local_media_path_maps_file_url():
    assert local_media_path("file:///mnt/movies/Inception.mkv") == "/mnt/movies/Inception.mkv"
    assert local_media_path("file:///home/a/Movie%20Night.mp4") == "/home/a/Movie Night.mp4"


def test_local_media_path_rejects_non_local_sources():
    assert local_media_path("https://youtube.com/watch?v=dQw4w9WgXcQ") is None
    assert local_media_path("some bare title") is None
    assert local_media_path(None) is None


# ---- ffmpeg range extraction ----

class _Result:
    def __init__(self, stdout=b"", returncode=0, stderr=b""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def test_extract_ranges_pcm_command_shape():
    calls = []

    def fake_run(cmd, capture_output):
        calls.append(cmd)
        return _Result(stdout=b"\x00" * 16)

    pcm = extract_ranges_pcm("/media/a.mp4", [[0, 1_000_000], [3_000_000, 3_500_000]],
                             ffmpeg="/usr/bin/ffmpeg", run=fake_run)
    assert pcm == b"\x00" * 32
    assert len(calls) == 2

    def _arg(cmd, flag):
        return cmd[cmd.index(flag) + 1]

    first = calls[0]
    assert first[0] == "/usr/bin/ffmpeg"
    assert first[first.index("-i") + 1] == "/media/a.mp4"
    assert _arg(first, "-ss") == "0.000" and _arg(first, "-t") == "1.000"
    assert _arg(first, "-ac") == "1" and _arg(first, "-ar") == "16000"
    assert _arg(first, "-f") == "f32le"
    assert "-vn" in first and first[-1] == "-"  # raw PCM to stdout
    second = calls[1]
    assert _arg(second, "-ss") == "3.000" and _arg(second, "-t") == "0.500"


def test_extract_ranges_pcm_skips_degenerate_ranges():
    calls = []
    pcm = extract_ranges_pcm("/m/a.mp4", [[0, 0], [5_000_000, 5_000_000]],
                             ffmpeg="/usr/bin/ffmpeg",
                             run=lambda cmd, capture_output: calls.append(cmd) or _Result())
    assert pcm is None and calls == []


def test_extract_ranges_pcm_fails_soft_on_missing_ffmpeg_and_errors(monkeypatch):
    monkeypatch.setattr("heimdall.capture.asr.shutil.which", lambda name: None)
    assert extract_ranges_pcm("/m/a.mp4", [[0, 1_000_000]]) is None
    assert extract_ranges_pcm("/m/a.mp4", [[0, 1_000_000]],
                              ffmpeg="/usr/bin/ffmpeg",
                              run=lambda cmd, capture_output: _Result(returncode=1, stderr=b"boom")) is None


def _sine_wav(path, seconds: int, rate: int = 16000, freq: float = 440.0):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(seconds * rate):
            sample = int(0.5 * 32767 * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", sample)
        w.writeframes(frames)


def test_extract_ranges_pcm_only_watched_audio(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    path = tmp_path / "clip.wav"
    _sine_wav(path, 3)
    pcm = extract_ranges_pcm(str(path), [[0, 500_000], [2_000_000, 2_500_000]])
    assert pcm is not None
    # Two 0.5s chunks of 16 kHz f32 mono: the watched total is 1.0s (~64 KB),
    # so the skipped 1.5s gap contributes no audio (< the full 3s would be 192 KB).
    assert len(pcm) > 40_000
    assert len(pcm) < 96_000


# ---- AsrManager job flow ----

def _session(*, source="file:///mnt/movies/Inception.mkv", live=0, transcript=None,
             source_name="captions"):
    return {
        "id": 1, "live": live, "media_source": source,
        "transcript": transcript, "transcript_source": source_name if transcript else None,
        "cues_json": None, "ranges": [[600_000_000, 900_000_000]],
    }


class _FakeDb:
    def __init__(self, session):
        self.session = session

    def get_watch_session(self, session_id):
        if self.session is None or self.session["id"] != session_id:
            return None
        return dict(self.session)

    def update_session_transcript(self, row_id, *, cues_json, transcript, transcript_source):
        self.session["cues_json"] = cues_json
        self.session["transcript"] = transcript
        self.session["transcript_source"] = transcript_source


def _manager(tmp_path, session, monkeypatch, text="I watched the movie"):
    db = _FakeDb(session)
    mgr = AsrManager(Config(data_dir=tmp_path), db)
    calls = {"extract": []}

    def fake_extract(path, ranges):
        calls["extract"].append((path, ranges))
        return b"\x00" * 64

    monkeypatch.setattr("heimdall.capture.asr.extract_ranges_pcm", fake_extract)
    monkeypatch.setattr(AsrEngine, "transcribe", lambda self, pcm: text)
    return mgr, db, calls


def _wait_until(cond, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def test_request_returns_cached_transcript_without_rerunning(tmp_path, monkeypatch):
    mgr, db, calls = _manager(tmp_path, _session(transcript="already captioned"), monkeypatch)
    code, body = mgr.request(1)
    assert code == 200
    assert body["transcript"] == "already captioned"
    assert body["transcript_source"] == "captions"
    assert calls["extract"] == []


def test_request_404_409_422(tmp_path, monkeypatch):
    mgr, _, _ = _manager(tmp_path, None, monkeypatch)
    assert mgr.request(1) == (404, {"detail": "session 1 not found"})

    mgr, _, _ = _manager(tmp_path, _session(live=1), monkeypatch)
    code, body = mgr.request(1)
    assert code == 409 and "in progress" in body["detail"]

    mgr, _, _ = _manager(tmp_path, _session(source="https://youtube.com/watch?v=dQw4w9WgXcQ"),
                         monkeypatch)
    code, body = mgr.request(1)
    assert code == 422 and "local media file" in body["detail"]


def test_request_runs_job_caches_result_and_never_reruns(tmp_path, monkeypatch):
    mgr, db, calls = _manager(tmp_path, _session(), monkeypatch)
    code, body = mgr.request(1)
    assert code == 202
    assert body["job"]["status"] in ("queued", "running")

    _wait_until(lambda: db.session.get("transcript") is not None)
    code, body = mgr.request(1)
    assert code == 200
    assert body["transcript"] == "I watched the movie"
    assert body["transcript_source"] == "asr"
    assert body["cues_json"] is None
    assert calls["extract"] == [("/mnt/movies/Inception.mkv", [[600_000_000, 900_000_000]])]

    code, body = mgr.request(1)  # cached -> instant, no new job
    assert code == 200
    assert len(calls["extract"]) == 1


def test_request_records_failure_then_retries(tmp_path, monkeypatch):
    mgr, db, calls = _manager(tmp_path, _session(), monkeypatch)
    monkeypatch.setattr("heimdall.capture.asr.extract_ranges_pcm",
                        lambda path, ranges: None)

    code, body = mgr.request(1)
    assert code == 202
    _wait_until(lambda: mgr._jobs.get(1, {}).get("status") == "failed")
    assert "extraction failed" in mgr._jobs[1]["error"]

    code, body = mgr.request(1)  # failed -> re-queued on the next request
    assert code == 202
    assert body["job"]["status"] == "queued"
