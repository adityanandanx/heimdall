"""Linear StateGraph pipe: 3 nodes, same steps as the plain version.

PROTOTYPE — wipe me. Variant B of ticket #4.
Shows the LangGraph-idiomatic equivalent of the plain function, using
with_structured_output (per ticket #3) and a checkpointer.
"""

import json
import time
from pathlib import Path
from typing import Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langfuse import observe
from pydantic import BaseModel, Field

from core import BASE_URL, MODEL, SYSTEM_PROMPT, build_prompt, render_markdown
from lf import finish, trace_url
from scratch import load_frames

OUT = Path(__file__).parent / "out"


class Category(BaseModel):
    name: str = Field(description="activity category, e.g. 'Building project', 'Research'")
    minutes: int = Field(description="rough minutes spent")
    detail: str = Field(description="one-line detail")


class Recap(BaseModel):
    date: str
    summary: str
    categories: list[Category]
    highlights: list[str]


class PipeState(TypedDict):
    frames: list[dict]
    recap: dict | None
    md: str | None
    path: str | None


@observe(name="load")
def load_node(state: PipeState) -> dict:
    t0 = time.perf_counter()
    frames = load_frames()
    print(f"  \x1b[1mload\x1b[0m      direct sqlite, {len(frames)} frames in {time.perf_counter()-t0:.3f}s")
    return {"frames": frames}


@observe(name="summarize-llm", as_type="generation")
def summarize_node(state: PipeState) -> dict:
    t0 = time.perf_counter()
    llm = ChatOpenAI(
        model=MODEL,
        base_url=BASE_URL,
        api_key="llama.cpp",
        temperature=0,
        max_retries=0,
        timeout=300,
    )
    structured = llm.with_structured_output(Recap, method="json_schema")
    prompt = build_prompt(state["frames"])
    result = structured.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)])
    dt = time.perf_counter() - t0
    recap = result.model_dump()
    print(f"  \x1b[1msummarize\x1b[0m  LLM round-trip {dt:.1f}s, {len(recap['categories'])} categories (structured output)")
    return {"recap": recap}


@observe(name="write")
def write_node(state: PipeState) -> dict:
    md = render_markdown(state["recap"])
    OUT.mkdir(exist_ok=True)
    path = OUT / "linear.md"
    path.write_text(md)
    print(f"  \x1b[1mwrite\x1b[0m     {path} ({len(md)} chars)")
    return {"md": md, "path": str(path)}


@observe(name="pipe-linear")
def run() -> dict:
    print("\x1b[1m[graph] linear StateGraph: load -> summarize -> write\x1b[0m")
    g = StateGraph(PipeState)
    g.add_node("load", load_node)
    g.add_node("summarize", summarize_node)
    g.add_node("write", write_node)
    g.add_edge(START, "load")
    g.add_edge("load", "summarize")
    g.add_edge("summarize", "write")
    g.add_edge("write", END)

    checkpointer = MemorySaver()
    app = g.compile(checkpointer=checkpointer)
    print("  compiled with MemorySaver checkpointer")

    t0 = time.perf_counter()
    config = {"configurable": {"thread_id": "recap-2026-08-02"}}
    final = app.invoke({"frames": [], "recap": None, "md": None, "path": None}, config)
    dt = time.perf_counter() - t0
    print(f"  \x1b[1mtotal\x1b[0m {dt:.1f}s across graph")
    # checkpointing demo: resume with an edited prompt from the saved state
    print("  \x1b[2mcheckpoint: state has", len(final["frames"]), "frames, recap written to", final["path"], "\x1b[0m")
    url = trace_url()
    print(f"  \x1b[36mtrace: {url}\x1b[0m")
    return {"variant": "linear", "frames": len(final["frames"]), "total_secs": round(dt, 1), "recap": final["recap"]}


if __name__ == "__main__":
    from scratch import seed

    seed()
    try:
        print(json.dumps(run(), indent=2, default=str))
    finally:
        finish()
