"""Run all three pipe variants back-to-back. PROTOTYPE — wipe me."""

import subprocess
import sys
from pathlib import Path

from scratch import seed

ROOT = Path(__file__).parent


def main() -> None:
    seed()
    for script in ["pipe_plain.py", "pipe_langgraph_linear.py", "pipe_langgraph_agent.py"]:
        print("\n" + "=" * 60)
        print(f"RUN {script}")
        print("=" * 60)
        subprocess.run([sys.executable, str(ROOT / script)], check=False)


if __name__ == "__main__":
    main()
