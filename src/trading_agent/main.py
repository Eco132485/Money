"""Autonomous dual-market orchestration. All orders route only to PaperBroker."""
from __future__ import annotations
import logging
import signal
import sys
import time
from typing import Dict, List, Optional

from .config import settings, LOG_DIR
from .db import get_db
from .exchange.binance import get_market_data
from .exchange.forex import YahooForexMarketData
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
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_DIR / "agent.log")],
)
log = logging.getLogger("agent")


def reconcile_paper_state(db, broker: PaperBroker, risk: RiskManager) -> None:
    """Reconcile the durable broker ledger with durable trade rows after a crash."""
    positions = dict(broker.positions)
    open_trades = db.open_trades()
    trades_by_symbol = {trade["symbol"]: trade for trade in open_trades}

    # A broker fill may have persisted just before the process crashed, before
    # the trade row was committed. Rebuild a conservative protective trade row.
    for symbol, position in positions.items():
        if symbol in trades_by_symbol:
            continue
        side = position.get("side", "long")
        entry = float(position["avg_price"])
        if side == "short":
            trade_side = "sell"
            stop = entry * (1 + settings.risk.stop_loss_pct)
            target = entry * (1 - settings.risk.take_profit_pct)
        else:
            trade_side = "buy"
            stop = entry * (1 - settings.risk.stop_loss_pct)
            target = entry * (1 + settings.risk.take_profit_pct)
        db.open_trade(symbol, trade_side, float(position["qty"]), entry,
                      "restart_recovery", stop, target)
        db.log("WARNING", "recovery",
               f"Reconstructed missing trade record for persisted {trade_side} position {symbol}")

    # A trade row without a broker position means the two ledgers disagree.
    # Do not invent an exit price or P/L: trip the kill switch for manual review.
    for trade in open_trades:
        if trade["symbol"] not in positions:
            reason = f"orphaned trade record for {trade['symbol']}; broker position missing"
            risk.trigger_kill_switch(reason)
            db.log("CRITICAL", "recovery", reason)



class TradingAgent:
    def __init__(self):
        self.db = get_db()
        self.crypto_market = get_market_data()
        self.forex_market = YahooForexMarketData()
        self.broker = PaperBroker(initial_balance=1000.0, state_store=self.db)
        self.risk = RiskManager()
        reconcile_paper_state(self.db, self.broker, self.risk)
        self.executor = TradeExecutor(self.broker, self.risk, self.db)
        self.engine = StrategyEngine()
        self.monitor = Monitor(self.db)
        self.improver = SelfImprover(self.engine, self.db)
        self.running = False
        self.cycle = 0
        self.last_improve = 0.0

    def _market_items(self):
        for symbol in settings.runtime.symbols:
            yield self.crypto_market, symbol, symbol
        for symbol in settings.runtime.forex_symbols:
            yield self.forex_market, symbol, f"FX:{symbol}"

    def _prices(self) -> Dict[str, float]:
        prices = {}
        for market, raw_symbol, portfolio_symbol in self._market_items():
            try:
                prices[portfolio_symbol] = market.get_ticker(raw_symbol).price
            except Exception as exc:
                log.warning("market quote unavailable for %s: %s", portfolio_symbol, type(exc).__name__)
        return prices

    def _process_symbol(self, market, raw_symbol: str, portfolio_symbol: str, prices: Dict[str, float]) -> None:
        candles = market.get_klines(raw_symbol, settings.runtime.timeframe, 300)
        if len(candles) < 30:
            raise ValueError(f"insufficient candles for {portfolio_symbol}")
        interval_seconds = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
                            "1h": 3600, "4h": 14400, "1d": 86400}.get(settings.runtime.timeframe)
        if interval_seconds is None:
            raise ValueError(f"unsupported timeframe: {settings.runtime.timeframe}")
        candle_age = time.time() - (candles[-1].ts / 1000.0)
        if candle_age > interval_seconds * 2:
            raise ValueError(f"stale market candles for {portfolio_symbol}")
        df = candles_to_df(candles)
        view = analyze(candles, portfolio_symbol)
        candidate = self.engine.generate(df)

        # AI is the decision authority. Missing key, free-tier confirmation,
        # quota, network failure or malformed output means HOLD, never fallback.
        ai = llm_client.reason_signal(view.to_dict(), candidate.to_dict())
        action = ai["action"]
        confidence = ai["confidence"]
        rationale = ai["rationale"]
        self.db.record_signal(portfolio_symbol, "gemini-3.8-flash", action,
                              confidence, view.price, {"market": view.to_dict(), "rationale": rationale})

        # Keep the per-cycle price snapshot shared across both markets. Missing
        # quotes block new entries so exposure cannot be understated.
        expected = [key for _, _, key in self._market_items()]
        prices_complete = all(key in prices for key in expected)
        equity = self.broker.equity(prices)
        exposure = self.broker.exposure(prices)
        position_qty = self.broker.position_qty(portfolio_symbol)
        position_side = self.broker.position_side(portfolio_symbol)
        is_forex = portfolio_symbol.startswith("FX:")

        if action == "buy" and position_side == "short":
            self.executor.cover_short(portfolio_symbol, position_qty, view.price, reason="AI buy signal")
        elif action == "buy" and position_side is None and prices_complete:
            decision = self.risk.pre_trade_check(
                equity=equity, price=view.price, confidence=confidence,
                current_exposure=exposure, open_positions=len(self.db.open_trades()),
                day_start_equity=self.db.day_start_equity(),
                peak_equity=self.db.peak_equity() or equity,
                stop_loss=candidate.stop_loss, take_profit=candidate.take_profit,
            )
            if decision.approved:
                result = self.executor.buy(portfolio_symbol, decision, view.price,
                                           candidate.strategy, confidence)
                if result and result.ok:
                    self.monitor.alert(
                        f"PAPER BUY {portfolio_symbol} @ {view.price:.6f} "
                        f"confidence={confidence:.2f} | {rationale}"
                    )
            else:
                self.db.record_order(portfolio_symbol, "buy", 0, view.price, "rejected",
                                     "paper", reason=decision.reason, confidence=confidence)
        elif action == "sell" and position_side == "long":
            self.executor.sell(portfolio_symbol, position_qty, view.price, reason="AI sell signal")
        elif action == "sell" and position_side is None and is_forex and prices_complete:
            decision = self.risk.pre_trade_check(
                equity=equity, price=view.price, confidence=confidence,
                current_exposure=exposure, open_positions=len(self.db.open_trades()),
                day_start_equity=self.db.day_start_equity(),
                peak_equity=self.db.peak_equity() or equity,
                stop_loss=candidate.stop_loss, take_profit=candidate.take_profit,
                side="sell",
            )
            if decision.approved:
                self.executor.open_short(portfolio_symbol, decision, view.price,
                                         candidate.strategy, confidence)
            else:
                self.db.record_order(portfolio_symbol, "sell", 0, view.price, "rejected",
                                     "paper", reason=decision.reason, confidence=confidence)

        log.info("%s price=%.6f AI=%s confidence=%.2f", portfolio_symbol,
                 view.price, action, confidence)

    def run_cycle(self) -> None:
        self.cycle += 1
        # Manage exits first, using one shared fresh quote snapshot.
        prices = self._prices()
        self.executor.manage_exits(prices)

        for market, raw_symbol, portfolio_symbol in self._market_items():
            try:
                self._process_symbol(market, raw_symbol, portfolio_symbol, prices)
            except Exception as exc:
                log.exception("error processing %s: %s", portfolio_symbol, exc)
                self.db.log("ERROR", "agent", f"{portfolio_symbol}: {type(exc).__name__}")

        prices = self._prices()
        equity = self.broker.equity(prices)
        exposure = self.broker.exposure(prices)
        self.db.record_equity(equity, self.broker.cash, exposure, "paper")
        log.info("cycle %d equity=%.2f cash=%.2f exposure=%.2f markets=forex+crypto",
                 self.cycle, equity, self.broker.cash, exposure)

        if time.time() - self.last_improve > 1800:
            self.last_improve = time.time()
            try:
                first_market, first_symbol, _ = next(self._market_items())
                df = candles_to_df(first_market.get_klines(first_symbol, settings.runtime.timeframe, 500))
                self.improver.review_and_update(self.engine.backtest_all(df))
            except Exception as exc:
                log.warning("self-improvement failed: %s", type(exc).__name__)

    def run(self, max_cycles: Optional[int] = None) -> None:
        self.running = True
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        log.info("ISA starting PAPER ONLY: virtual_equity=$1000 forex=%s crypto=%s AI=%s",
                 settings.runtime.forex_symbols, settings.runtime.symbols, llm_client.available)
        self.monitor.alert("ISA paper trader started; live trading is disabled.")
        while self.running:
            try:
                self.run_cycle()
            except Exception as exc:
                log.exception("cycle error: %s", type(exc).__name__)
            if max_cycles is not None and self.cycle >= max_cycles:
                break
            time.sleep(max(5, settings.runtime.loop_interval_sec))
        log.info("agent stopped after %d cycles", self.cycle)

    def stop(self) -> None:
        self.running = False


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="ISA dual-market paper trading agent")
    parser.add_argument("--cycles", type=int, default=None)
    args = parser.parse_args()
    TradingAgent().run(max_cycles=args.cycles)


if __name__ == "__main__":
    main()
