"""Entry point for `python -m osop_mcp`."""
import asyncio
import sys
from pathlib import Path

# Ensure the package root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from server.main import main

if __name__ == "__main__":
    asyncio.run(main())
