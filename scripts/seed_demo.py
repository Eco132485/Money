#!/usr/bin/env python3
"""Seed a demo database with synthetic data for dashboard previews.

This is NOT real trading data — it only exists to showcase the UI. Point the
dashboard at the generated DB with DB_PATH=data/demo.db.
"""
from __future__ import annotations

import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_agent.db import Database

random.seed(7)


def main(path: str = "data/demo.db"):
    db = Database(path)
    now = time.time()
    equity = 10000.0
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    actions = ["buy", "sell", "hold"]

    # equity curve: gentle uptrend with noise over ~48h
    for i in range(96):
        equity *= 1 + random.gauss(0.0012, 0.004)
        db.record_equity(round(equity, 2), round(equity * 0.7, 2),
                         round(equity * 0.3, 2), "paper")

    # signals
    for i in range(24):
        sym = random.choice(symbols)
        act = random.choices(actions, weights=[0.35, 0.2, 0.45])[0]
        db.record_signal(sym, random.choice(["trend_follow", "mean_reversion", "breakout"]),
                         act, round(random.uniform(0.4, 0.9), 2),
                         round(random.uniform(2000, 78000), 2), {"demo": True})

    # closed trades
    for i in range(18):
        sym = random.choice(symbols)
        entry = random.uniform(2000, 78000)
        win = random.random() < 0.6
        pnl_pct = random.uniform(0.005, 0.04) * (1 if win else -1)
        exit_price = entry * (1 + pnl_pct)
        qty = 100 / entry
        tid = db.open_trade(sym, "buy", qty, entry, random.choice(["trend_follow", "mean_reversion", "breakout"]),
                            entry * 0.985, entry * 1.03)
        db.close_trade(tid, exit_price, qty * (exit_price - entry), pnl_pct)

    # a couple of open positions
    for sym in ["BTCUSDT", "ETHUSDT"]:
        entry = random.uniform(2000, 78000)
        db.open_trade(sym, "buy", 100 / entry, entry, "trend_follow", entry * 0.985, entry * 1.03)

    db.log("INFO", "demo", "Demo data seeded for dashboard preview")
    print(f"seeded {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/demo.db")
