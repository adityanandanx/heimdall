# PROTOTYPE — Gemma 4 E2B QAT on Intel Arc Vulkan (measurements)

Throwaway benchmark for ticket "Gemma 4 on Intel Arc Vulkan runtime viability". Wipe me.

## Setup

- llama-server v10182, model `google/gemma-4-E2B-it-qat-q4_0-gguf` (`gemma-4-E2B_q4_0-it.gguf`, rev `675cff42`, 3.35 GB), Intel Arc (Meteor Lake, MTL) Vulkan, 30 GB RAM (17 free).
- Run: `./start.sh 99` (or `0` for CPU). Benchmark: `uv run python bench.py <samples>`.

## Results

| Metric | Vulkan `-ngl 99` | CPU `-ngl 0` |
|---|---|---|
| Generation | ~18.1 tok/s | ~13.5 tok/s |
| RSS | ~2.3 GB | ~3.4 GB |
| Model load | ~2 s | ~2 s |
| MESA "experimental Xe KMD" warning | benign, non-fatal | n/a |
| JSON (with `response_format`) | 5/5 parse | valid |

TTFT ~0.2–0.4 s (llama-server `timings.prompt_n` is unreliable; wall-based).

## Findings

1. **Vulkan works** on this build — no crash. MESA warning is noise.
2. **`response_format` matters**: without it the model wraps valid JSON in ```` ```json ```` fences (0/5 `json.loads`); with `{"type":"json_object"}` → 5/5 clean parse. With `json_schema` + Pydantic it's both grammar-enforced and schema-validated.
3. **Thinking block is the trap**: disabled globally → `reasoning_content` empty, clean output. Enabled (per-request override) → `content` **empty**, all tokens go to `reasoning_content` (~5x overhead, 28 s wall). This build deprecates `--chat-template-kwargs '{"enable_thinking":false}'` → use **`--reasoning off`**.
4. Model is fast enough for batch/scheduled pipes; a full day-recap prompt will be far larger than this test, so keep pipe output bounded (schema + max tokens).

## Verdict (locked on the ticket)

- Offload: **Vulkan only** (`-ngl 99`). CPU `-ngl 0` measured working as an undocumented escape hatch.
- Thinking: `--reasoning off`.
- Structured output: `with_structured_output(PydanticSchema, method="json_schema")`; malformed/`ValidationError` rate over a 100-record sample is the 12B upgrade-bar signal (>10%).
