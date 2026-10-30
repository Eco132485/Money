#!/usr/bin/env python3
"""Run a full backtest across all strategies for one or more symbols."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_agent.config import settings
from trading_agent.exchange.binance import get_market_data
from trading_agent.market_analysis import candles_to_df, analyze
from trading_agent.strategy_engine import StrategyEngine


def main():
    parser = argparse.ArgumentParser(description="Backtest strategies")
    parser.add_argument("--symbols", default=",".join(settings.runtime.symbols))
    parser.add_argument("--timeframe", default=settings.runtime.timeframe)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--fee", type=float, default=0.001)
    args = parser.parse_args()

    market = get_market_data()
    engine = StrategyEngine()
    all_results = {}

    for symbol in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        print(f"\n=== {symbol} ({args.timeframe}) ===")
        candles = market.get_klines(symbol, args.timeframe, args.limit)
        df = candles_to_df(candles)
        view = analyze(candles, symbol)
        print(f"price={view.price:.2f} trend={view.trend} regime={view.regime} "
              f"rsi={view.rsi:.1f} adx={view.adx:.1f} atr%={view.atr_pct:.3f}")
        results = engine.backtest_all(df, fee=args.fee)
        all_results[symbol] = results
        print(f"{'strategy':<16}{'return':>10}{'sharpe':>9}{'maxDD':>9}{'win%':>8}{'PF':>7}{'trades':>8}")
        for name, m in results.items():
            if "error" in m:
                print(f"{name:<16}  {m['error']}")
                continue
            print(f"{name:<16}{m['total_return']:>10.2%}{m['sharpe']:>9.2f}"
                  f"{m['max_drawdown']:>9.2%}{m['win_rate']:>8.1%}"
                  f"{m['profit_factor']:>7.2f}{m['num_trades']:>8}")

    print("\n" + json.dumps(all_results, indent=2))


if __name__ == "__main__":
    main()
