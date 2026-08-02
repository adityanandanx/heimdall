#!/usr/bin/env python3
# PROTOTYPE — measure Gemma 4 E2B QAT via llama-server on Vulkan (throwaway)
import json, sys, time, urllib.request, os

BASE = "http://127.0.0.1:8080/v1/chat/completions"
SAMPLES = int(sys.argv[1]) if len(sys.argv) > 1 else 5

OCR_BODY = """today's screen log (OCR of frames):
- 09:12 activewindow: firefox — "Heimdall - gemma 4 vulkan benchmark search"
- 09:47 activewindow: code — "src/heimdall/db.py" researching SQLite FTS5 rank
- 10:20 activewindow: firefox — "huggingface google gemma-4-E2B-it-qat-q4_0-gguf"
- 11:05 activewindow: alacritty — "uv add langgraph langchain-openai"
- 12:30 activewindow: firefox — "intel arc vulkan mesa xe kmd github"
- 13:00 activewindow: firefox — "linkedin jobs remote backend rust"
- 14:10 activewindow: ytmusic — "lo-fi hip hop radio - beats to relax/study"
- 15:00 activewindow: code — "src/heimdall/pipes/day_recap.py" testing prompt
- 16:45 activewindow: firefox — "gemma 4 12b vs e2b benchmark structured json"
- 17:30 activewindow: alacritty — "git commit -m 'trim architecture to screen-only'"
"""

SYSTEM = "Respond only with raw JSON. Do not include any thinking, analysis, or explanation."
USER = ("From the OCR screen log below, produce a JSON object with exactly "
        "these keys: \"accomplishments\" (list of strings), \"unfinished\" (list), "
        "\"standout_time\" (string, one app+reason), \"time_breakdown\" (object mapping "
        "category to minutes). Categories: building, research, jobs, entertainment, dsa.\n\n"
        "LOG:\n" + OCR_BODY)

def req():
    body = {
        "model": "gemma-4-E2B-it-qat-q4_0-gguf",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER},
        ],
        "temperature": 0.0,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(body).encode()
    r = urllib.request.Request(BASE, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=120) as resp:
        return json.loads(resp.read())

rss_kb = -1
def mem():
    global rss_kb
    import subprocess
    try:
        pid = subprocess.check_output(["pgrep", "-f", "llama-server.*8080"]).decode().strip().split("\n")[0]
        for line in open(f"/proc/{pid}/status"):
            if line.startswith("VmRSS:"):
                rss_kb = int(line.split()[1])
                return rss_kb // 1024
    except Exception:
        pass
    return -1

def main():
    ok = 0; malformed = 0; thinking = 0; empty = 0
    totals = {"prompt_n": 0, "prompt_ms": 0, "pred_n": 0, "pred_ms": 0}
    first = None
    for i in range(SAMPLES):
        t0 = time.time()
        r = req()
        wall = time.time() - t0
        ch = r["choices"][0]
        content = ch["message"].get("content") or ""
        reasoning = ch["message"].get("reasoning_content") or ""
        tm = r.get("timings", {})
        pt = tm.get("prompt_n", 0); pms = tm.get("prompt_ms", 0.0)
        pn = tm.get("predicted_n", 0); dms = tm.get("predicted_ms", 0.0)
        totals["prompt_n"] += pt; totals["prompt_ms"] += pms
        totals["pred_n"] += pn; totals["pred_ms"] += dms
        parsed = None
        try:
            parsed = json.loads(content)
            ok += 1
        except Exception:
            malformed += 1
            if len(content.strip()) == 0:
                empty += 1
        if reasoning:
            thinking += 1
        if first is None:
            first = {"sample": i + 1, "content": content[:400], "reasoning": reasoning[:120],
                     "ptok": pt, "pms": round(pms, 1), "tok": pn, "ms": round(dms, 1),
                     "tps": round(pn / (dms / 1000), 1) if dms else -1,
                     "wall": round(wall, 2), "rss_mb": mem()}
        print(f"sample {i+1}: ok={bool(parsed)} tokens={pn} gen_ms={dms:.0f} "
              f"tps={pn/(dms/1000):.1f} wall={wall:.1f}s reasoning={bool(reasoning)}")
    n = max(1, SAMPLES)
    print("\n=== SUMMARY ===")
    print(f"JSON parse success : {ok}/{SAMPLES} ({ok/n:.0%})")
    print(f"malformed/empty    : {malformed}/{SAMPLES} (empty: {empty})")
    print(f"reasoning_content  : {thinking}/{SAMPLES}")
    print(f"prompt             : {totals['prompt_n']/n:.0f} tok, {totals['prompt_ms']/n:.0f} ms "
          f"-> TTFT {totals['prompt_ms']/n/1000:.2f}s")
    print(f"generation         : {totals['pred_n']/n:.0f} tok, "
          f"{totals['pred_n']/n / (totals['pred_ms']/n/1000):.1f} tok/s")
    print(f"RSS (llama-server) : {rss_kb // 1024 if rss_kb > 0 else 'n/a'} MB")
    print(f"\n--- first sample detail ---")
    print(json.dumps(first, indent=2, ensure_ascii=False))

main()
