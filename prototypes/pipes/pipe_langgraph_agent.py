"""Agent StateGraph pipe: LLM + db_search tool loop, checkpointed.

PROTOTYPE — wipe me. Variant C of ticket #4.
The case where LangGraph is *supposed* to pay off: the model decides what to
query instead of the prompt inlining every frame, and the graph loops until it
has what it needs. Checkpointed so the run is resumable / inspectable.
"""

import json
import time
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langfuse import observe

from core import BASE_URL, MODEL, build_tool_prompt, parse_recap, render_markdown
from lf import finish, trace_url
from scratch import db_search, load_frames, seed

OUT = Path(__file__).parent / "out"

# Tool-first system prompt: the shared SYSTEM_PROMPT ("produce the recap JSON")
# combined with a long tool directive made the model answer directly instead of
# calling tools. A tool-first framing keeps it querying.
AGENT_SYSTEM_PROMPT = (
    "You are Heimdall, a local screen-memory recap agent. You answer by FIRST "
    "querying your data tool — never answer directly from memory. Call db_search "
    "one or more times to retrieve the frames, then produce the recap. "
    "The user's known activities: building projects, researching, applying to "
    "jobs/internships, watching YouTube, movies, listening to music, practicing DSA."
)


@tool
def db_search_tool(q: str) -> str:
    """Query captured OCR frames by substring over window class or title. e.g. q='youtube'."""
    return db_search(q=q)


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


@observe(name="llm-turn", as_type="generation")
def call_model(state: AgentState) -> dict:
    llm = ChatOpenAI(
        model=MODEL,
        base_url=BASE_URL,
        api_key="llama.cpp",
        temperature=0,
        max_retries=0,
        timeout=300,
    ).bind_tools([db_search_tool])
    msg = llm.invoke(state["messages"])
    print(f"  \x1b[1mLLM\x1b[0m turn -> {msg.content[:60]!r} tool_calls={len(msg.tool_calls)}")
    return {"messages": [msg]}


@observe(name="tools")
def tools_node(state: AgentState) -> dict:
    out = []
    for tc in state["messages"][-1].tool_calls:
        name = tc["name"]
        args = tc["args"]
        print(f"  \x1b[1mtool\x1b[0m  db_search({args!r})")
        result = db_search(**args)
        out.append(ToolMessage(content=result, tool_call_id=tc["id"]))
    return {"messages": out}


def should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    return "tools" if last.tool_calls else END


@observe(name="pipe-agent")
def run(thread_id: str = "agent-recap-2026-08-02") -> dict:
    print("\x1b[1m[graph] agent StateGraph: LLM <-> db_search loop, checkpointed\x1b[0m")
    g = StateGraph(AgentState)
    g.add_node("llm", call_model)
    g.add_node("tools", tools_node)
    g.add_edge(START, "llm")
    g.add_conditional_edges("llm", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "llm")

    app = g.compile(checkpointer=MemorySaver())
    print("  compiled with MemorySaver checkpointer")

    frames = load_frames()
    prompt = build_tool_prompt(frames)
    config = {"configurable": {"thread_id": thread_id}}

    t0 = time.perf_counter()
    final = app.invoke(
        {"messages": [SystemMessage(content=AGENT_SYSTEM_PROMPT), HumanMessage(content=prompt)]},
        config,
    )
    dt = time.perf_counter() - t0

    recap = parse_recap(final["messages"][-1].content)
    md = render_markdown(recap)
    OUT.mkdir(exist_ok=True)
    path = OUT / "agent.md"
    path.write_text(md)

    print(f"  \x1b[1mtotal\x1b[0m {dt:.1f}s, {len(final['messages'])} messages, recap -> {path}")
    print("  \x1b[2mcheckpoint: thread_id='{0}' holds full message history\x1b[0m".format(thread_id))
    url = trace_url()
    print(f"  \x1b[36mtrace: {url}\x1b[0m")
    return {"variant": "agent", "frames": len(frames), "total_secs": round(dt, 1), "messages": len(final["messages"]), "recap": recap, "tool_calls": sum(len(getattr(m, "tool_calls", None) or []) for m in final["messages"])}


if __name__ == "__main__":
    seed()
    try:
        print(json.dumps(run(), indent=2, default=str))
    finally:
        finish()
