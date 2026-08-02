#!/usr/bin/env bash
# PROTOTYPE — Gemma 4 on Intel Arc Vulkan runtime viability (throwaway, wipe me)
set -u
MODEL="$HOME/.cache/huggingface/hub/models--google--gemma-4-E2B-it-qat-q4_0-gguf/snapshots/675cff42a74c774d6cb76f76d8eacb49b48c9b93/gemma-4-E2B_q4_0-it.gguf"
NGL="${1:-99}"
PORT="${2:-8080}"
LOG="$(dirname "$0")/llama-$NGL.log"
pkill -f "llama-server.*-ngl $NGL" 2>/dev/null
sleep 1
nohup /usr/bin/llama-server \
  -m "$MODEL" --host 127.0.0.1 --port "$PORT" \
  -ngl "$NGL" -c 8192 --jinja --no-mmproj --temp 0 \
  --chat-template-kwargs '{"enable_thinking":false}' \
  > "$LOG" 2>&1 &
echo "started llama-server (ngl=$NGL, port=$PORT), log: $LOG"
