# Prototype: LangGraph StateGraph vs plain-function pipes

**THROWAWAY — answers ticket #4, never ships.**

## Question

Is a LangGraph `StateGraph` genuinely the right pipe architecture for Heimdall,
or would a plain Python function that calls the LLM be simpler and just as good?

## The three variants

Same minimal pipe — *load frames → summarize with Gemma 4 → write markdown* —
built three ways against the same scratch DB (`scratch_pipes.sqlite3`, wipe me):

| Variant | File | What it shows |
|---|---|---|
| Plain function | `pipe_plain.py` | `httpx` + prompt string + `response_format` JSON |
| Linear StateGraph | `pipe_langgraph_linear.py` | same 3 steps as a 3-node graph |
| Agent StateGraph | `pipe_langgraph_agent.py` | LangGraph-idiomatic: LLM node + `db_search` tool loop, checkpointed |

## Prereqs

- llama-server serving Gemma 4 E2B QAT on `:8080` (Vulkan, per tickets #2/#3):
  `/usr/bin/llama-server -m <E2B QAT gguf> -ngl 99 -c 8192 --jinja --no-mmproj --temp 0 --reasoning off`
- venv with `httpx`, `langgraph`, `langchain-openai`

## Run

Seeds the scratch DB, then runs all three pipes back-to-back:

```
uv run python prototypes/pipes/run_all.py
```

Each variant prints its state as it goes and writes markdown to `out/`:

- `out/plain.md`, `out/linear.md`, `out/agent.md`

The honest comparison lives in `compare.md`.
