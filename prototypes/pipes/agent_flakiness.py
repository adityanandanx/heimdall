"""Re-run the agent pipe N times to quantify tool-call flakiness on 2B Gemma.

PROTOTYPE — wipe me. Each run is its own Langfuse trace (printed URL).
"""

import json
import time

from lf import finish
from pipe_langgraph_agent import run
from scratch import seed

N = 5


def main() -> None:
    seed()
    rows = []
    for i in range(N):
        print(f"\n=== run {i + 1}/{N} ===")
        t0 = time.perf_counter()
        res = run(thread_id=f"agent-flakiness-{i}")
        wall = time.perf_counter() - t0
        rows.append(
            {
                "run": i + 1,
                "total_secs": res["total_secs"],
                "messages": res["messages"],
                "tool_calls": res["tool_calls"],
                "recap_ok": res["recap"].get("date") is not None,
            }
        )
        print(json.dumps(rows[-1]))

    print("\n=== summary ===")
    for r in rows:
        print(r)
    used = sum(1 for r in rows if r["tool_calls"] > 0)
    print(f"tool-using runs: {used}/{N}")


if __name__ == "__main__":
    try:
        main()
    finally:
        finish()
