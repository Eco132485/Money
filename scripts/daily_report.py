#!/usr/bin/env python3
"""Generate a daily performance report from the database."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_agent.db import get_db
from trading_agent.monitoring import Monitor


def main():
    db = get_db()
    monitor = Monitor(db)
    equity_series = db.equity_series(limit=1)
    equity = equity_series[-1]["equity"] if equity_series else 0.0
    positions = {t["symbol"]: t for t in db.open_trades()}
    report = monitor.daily_report(equity, positions)
    print(report)
    print("\nPerformance:", json.dumps(monitor.performance(), indent=2))


if __name__ == "__main__":
    main()
