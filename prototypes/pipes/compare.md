# Pipes: plain function vs LangGraph StateGraph — honest comparison

Prototype for ticket #4. All three variants run the same 20 seeded frames
(mirroring Aditya's real windows) through Gemma 4 E2B QAT (q4_0) served by
llama-server on Vulkan, `--temp 0`, 8K ctx. Same prompt content; the variants
differ only in execution structure. All runs traced to self-hosted Langfuse
v4.1.0 (OTLP) — links below.

## The three variants

| variant | structure | lines |
|---|---|---|
| A plain | one function: sqlite load → one `httpx` POST with `response_format` schema → markdown | ~55 |
| B linear | 3-node StateGraph (load / summarize / write), `with_structured_output(Recap, json_schema)`, MemorySaver | ~105 |
| C agent | LLM + `db_search` tool loop, MemorySaver, tool-first system prompt | ~115 |

## Timing

| variant | wall time |
|---|---|
| plain | 26.4s / 27.5s |
| linear | 23.9s / 24.7s |
| agent (final) | 21.6–22.0s (5/5 runs × 4 tool calls) |

## Tool calling — the corrected finding

Gemma 4 E2B **is fully tool-capable** — the earlier "the agent never calls
tools (0/7)" conclusion was wrong. Two independent proofs:

- Direct API: a firm one-liner ("You MUST call the db_search tool") yields a
  tool call 3/3 times, deterministically.
- The agent loop with a tool-first system prompt: **5/5 runs, 4 `db_search`
  calls each**, valid recap every run.

The 0/7 failure was **my prompt bug**: the shared `SYSTEM_PROMPT` ("Produce a
structured day recap in JSON") pre-programmed the model to answer directly.
When combined with the tool directive, it reliably suppressed tool calls.
Removing that conflict fixed it — the limitation was the prompt, not the model.

The residual fragility is real and operational, on three surfaces that must be
engineered:

1. **Prompt alignment** — the system prompt must be tool-first; a recap-first
   framing silently degrades the agent into a plain pipe.
2. **Query generation** — the 2B model emits vocabulary phrases
   (`"watching youtube"`) instead of discriminative substrings (`"youtube"`).
3. **Retrieval design** — naive whole-phrase `LIKE` returned nothing for those
   phrases; token-tolerant matching fixed it (that is a real retrieval
   concern, not a model one).

After those two fixes the loop ran cleanly 5/5 — but it took two debugging
iterations (seen in the traces) to get there, and the output is still thinner
than the single-shot pipes (3 categories, misses build/research/movie, vs 5
complete categories for plain/linear). The tool loop trades full-context
prompting for retrieved fragments; on 20 inline-able frames that is a loss.

## Output quality (same day, same data)

| variant | categories | notes |
|---|---|---|
| plain / linear | 5 | complete: dev work, research, DSA, jobs, media — identical output |
| agent | 3 | jobs 180m, DSA 108m, entertainment 48m; misses build-work/research/movie |

## Complexity

- **Plain is the honest baseline.** Reads top-to-bottom; `response_format`
  returns schema-shaped JSON; parse succeeds every run.
- **Linear adds ceremony for zero behavioral change.** Same steps, same order,
  byte-identical output. The pydantic `Recap` model is the one genuine
  nicety — available without the graph.
- **Agent is the only variant where the graph earns its keep** (real
  conditional control flow) — and the model proves it can drive it. But that
  capability comes with three new failure surfaces (above) and, on a dataset
  this small, worse output than inlining the frames.

## Checkpointing

- Agent: genuinely valuable — the tool loop's message history is resumable and
  inspectable; this is where StateGraph's checkpointer pays.
- Linear: works (resume by thread_id, inspect state) but marginal for a fixed
  3-step nightly pipe.
- Plain: none; "re-run, it's idempotent".

## Debuggability / observability

- All three trace equally well into Langfuse via `@observe` (root span +
  nested GENERATION spans; node spans in B/C appear because node functions are
  observed — no LangGraph-specific integration needed). The agent iterations
  above were verified directly from the traces (tool-call args, retrieval
  results).
- Plain is the most inspectable in code: a linear function vs. graph dispatch.

## Dependency weight

| | deps | import cost |
|---|---|---|
| plain | httpx (748K) + stdlib | ~0.05s |
| linear / agent | langgraph (3.1M), langchain-core (4.8M), langchain-openai (1.1M), openai (19M), langchain (1.3M), pydantic, … (42 packages) | ~0.68s (`langchain_openai`) |

## Traces (self-hosted Langfuse at localhost:3000)

- plain: http://localhost:3000/project/539fa74e4fd7ae0b/traces/109d016889abb777aa801e7640ac4093
- linear: http://localhost:3000/project/539fa74e4fd7ae0b/traces/9080adf64b910b2703c21de95ea05a44
- agent, final design (5/5 × 4 tool calls, token-tolerant retrieval):
  - http://localhost:3000/project/539fa74e4fd7ae0b/traces/cf6ec50cc1cbb145c893ab4a59a14f1a
  - http://localhost:3000/project/539fa74e4fd7ae0b/traces/d563ad38b1560a4942b330f95bb94fc4
  - http://localhost:3000/project/539fa74e4fd7ae0b/traces/5482beb7a22025cca4479d1ae746cf26
  - http://localhost:3000/project/539fa74e4fd7ae0b/traces/359155ed74f4631edeba11e92a138cd8
  - http://localhost:3000/project/539fa74e4fd7ae0b/traces/19803a3e18091509d9f5af2a256aff8e
- agent, degenerate runs (for contrast; prompt-conflict → 0 tool calls, and
  naive retrieval → empty recap): `13b23e3fd16d`, `28622f05323b`,
  `660b8645fa72` (see full URL pattern above)

## Draft verdict (for HITL)

1. **v1 pipes are plain functions.** For fixed-step, deterministic recaps on a
   dataset that fits the prompt: `httpx` + `response_format` (+ optional
   pydantic validator). No LangGraph, no retrieval.
2. **Gemma can drive tools — keep the agent design as a documented option**,
   not a v1 requirement. It earns its complexity only when data exceeds the
   prompt budget or a feature genuinely needs conditional tool use — and it
   must ship with a tool-first system prompt and query-tolerant retrieval
   (both learned here).
3. **Checkpointing is only worth it when state is the product** (interactive,
   resumable sessions), which is the agent case, not the batch recap case.
