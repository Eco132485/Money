"""
Autonomous trading agent — main orchestration loop.

Each cycle, for every configured symbol:
  1. fetch market data
  2. analyze market regime / indicators
  3. generate an ensemble signal (optionally refined by an LLM)
  4. run risk checks and size the position
  5. execute (paper by default), record to DB
  6. manage open positions (stop/target)
  7. periodically run backtests + self-improvement and send reports
"""
from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Dict, List, Optional

from .config import settings, LOG_DIR
from .db import get_db
from .exchange.binance import get_market_data
from .exchange.paper import PaperBroker
from .llm import llm_client
from .market_analysis import analyze, candles_to_df
from .monitoring import Monitor
from .risk_management import RiskManager
from .self_improvement import SelfImprover
from .strategy_engine import StrategyEngine
from .trade_execution import TradeExecutor

logging.basicConfig(
    level=getattr(logging, settings.runtime.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "agent.log"),
    ],
)
log = logging.getLogger("agent")


class TradingAgent:
    def __init__(self):
        self.db = get_db()
        self.market = get_market_data()
        self.broker = PaperBroker(initial_balance=settings.runtime.initial_balance)
        self.risk = RiskManager()
        self.executor = TradeExecutor(self.broker, self.risk, self.db)
        self.engine = StrategyEngine()
        self.monitor = Monitor(self.db)
        self.improver = SelfImprover(self.engine, self.db)
        self.running = False
        self.cycle = 0
        self.last_improve = 0.0

    # ---- helpers ----
    def _prices(self, symbols: List[str]) -> Dict[str, float]:
        prices = {}
        for s in symbols:
            try:
                prices[s] = self.market.get_ticker(s).price
            except Exception as exc:
                log.warning("price fetch failed for %s: %s", s, exc)
        return prices

    def _process_symbol(self, symbol: str) -> None:
        candles = self.market.get_klines(symbol, settings.runtime.timeframe, 300)
        df = candles_to_df(candles)
        view = analyze(candles, symbol)
        signal = self.engine.generate(df)

        # optional LLM refinement
        if llm_client.available and signal.action != "hold":
            refined = llm_client.reason_signal(view.to_dict(), signal.to_dict())
            signal.action = refined.get("action", signal.action)
            signal.confidence = refined.get("confidence", signal.confidence)
            signal.rationale += f" | llm:{refined.get('rationale','')[:80]}"

        self.db.record_signal(symbol, signal.strategy, signal.action,
                              signal.confidence, view.price, view.to_dict())

        prices = self._prices(settings.runtime.symbols)
        equity = self.broker.equity(prices)
        exposure = self.broker.exposure(prices)

        if signal.action == "buy" and self.broker.position_qty(symbol) == 0:
            decision = self.risk.pre_trade_check(
                equity=equity, price=view.price, confidence=signal.confidence,
                current_exposure=exposure, open_positions=len(self.db.open_trades()),
                day_start_equity=self.db.day_start_equity(),
                peak_equity=self.db.peak_equity() or equity,
                stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            )
            if decision.approved:
                self.executor.buy(symbol, decision, view.price, signal.strategy, signal.confidence)
                self.monitor.alert(
                    f"BUY {symbol} @ {view.price:.2f} conf={signal.confidence:.2f} ({signal.strategy})"
                )
        elif signal.action == "sell" and self.broker.position_qty(symbol) > 0:
            self.executor.sell(symbol, self.broker.position_qty(symbol), view.price, reason="signal")

        log.info("%s price=%.2f trend=%s regime=%s signal=%s conf=%.2f",
                 symbol, view.price, view.trend, view.regime, signal.action, signal.confidence)

    # ---- main loop ----
    def run_cycle(self) -> None:
        self.cycle += 1
        symbols = settings.runtime.symbols
        for symbol in symbols:
            try:
                self._process_symbol(symbol)
            except Exception as exc:
                log.exception("error processing %s: %s", symbol, exc)
                self.db.log("ERROR", "agent", f"{symbol}: {exc}")

        prices = self._prices(symbols)
        self.executor.manage_exits(prices)
        equity = self.broker.equity(prices)
        exposure = self.broker.exposure(prices)
        self.db.record_equity(equity, self.broker.cash, exposure, settings.runtime.mode)
        log.info("cycle %d equity=%.2f cash=%.2f exposure=%.2f",
                 self.cycle, equity, self.broker.cash, exposure)

        # periodic self-improvement (every ~30 min)
        if time.time() - self.last_improve > 1800:
            self.last_improve = time.time()
            try:
                df = candles_to_df(self.market.get_klines(symbols[0], settings.runtime.timeframe, 500))
                bt = self.engine.backtest_all(df)
                self.improver.review_and_update(bt)
            except Exception as exc:
                log.warning("self-improvement failed: %s", exc)

    def run(self, max_cycles: Optional[int] = None) -> None:
        self.running = True
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        log.info("agent starting: mode=%s symbols=%s tf=%s",
                 settings.runtime.mode, settings.runtime.symbols, settings.runtime.timeframe)
        self.monitor.alert(f"Trading agent started (mode={settings.runtime.mode})")
        while self.running:
            try:
                self.run_cycle()
            except Exception as exc:
                log.exception("cycle error: %s", exc)
            if max_cycles and self.cycle >= max_cycles:
                break
            time.sleep(settings.runtime.loop_interval_sec)
        log.info("agent stopped after %d cycles", self.cycle)

    def stop(self) -> None:
        self.running = False


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Autonomous trading agent")
    parser.add_argument("--cycles", type=int, default=None, help="run N cycles then exit")
    args = parser.parse_args()
    TradingAgent().run(max_cycles=args.cycles)


if __name__ == "__main__":
    main()
