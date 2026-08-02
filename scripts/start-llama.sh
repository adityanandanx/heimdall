#!/usr/bin/env bash
# Launch the local Gemma 4 E2B QAT model on the Intel Arc Vulkan backend.
# Flags are LOCKED by spec ticket #3 — do not change without re-verifying.
#
# Usage:  scripts/start-llama.sh [--port 8080]
# Env:    HEIMDALL_MODEL  path to the gguf (defaults to the cached E2B QAT)
set -euo pipefail

MODEL="${HEIMDALL_MODEL:-$HOME/.cache/huggingface/hub/models--google--gemma-4-E2B-it-qat-q4_0-gguf/snapshots/675cff42a74c774d6cb76f76d8eacb49b48c9b93/gemma-4-E2B_q4_0-it.gguf}"
PORT="8080"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -r "$MODEL" ]]; then
  echo "model not found: $MODEL" >&2
  echo "set HEIMDALL_MODEL to your gemma-4-E2B-it-qat-q4_0 gguf" >&2
  exit 1
fi

exec /usr/bin/llama-server \
  -m "$MODEL" \
  --port "$PORT" \
  -ngl 99 \
  -c 8192 \
  --jinja \
  --no-mmproj \
  --temp 0 \
  --reasoning off
