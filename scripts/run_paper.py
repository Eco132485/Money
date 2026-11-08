#!/usr/bin/env python3
"""Run the autonomous agent in paper-trading mode for a bounded number of cycles."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_agent.config import settings
from trading_agent.main import TradingAgent


def main():
    parser = argparse.ArgumentParser(description="Run paper trading agent")
    parser.add_argument("--cycles", type=int, default=5, help="number of cycles to run")
    parser.add_argument("--interval", type=int, default=None, help="seconds between cycles")
    args = parser.parse_args()

    if args.interval is not None:
        settings.runtime.loop_interval_sec = args.interval
    settings.runtime.mode = "paper"

    agent = TradingAgent()
    agent.run(max_cycles=args.cycles)


if __name__ == "__main__":
    main()
