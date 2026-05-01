import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.client import LocalPrintAgent


if __name__ == "__main__":
    asyncio.run(LocalPrintAgent().run_forever())
