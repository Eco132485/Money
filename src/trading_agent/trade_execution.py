"""
Trade execution: routes approved orders to the paper broker (default) or a
live exchange adapter, records everything, and enforces risk at the boundary.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .config import settings
from .db import Database, get_db
from .exchange.base import OrderResult
from .exchange.paper import PaperBroker
from .risk_management import RiskManager, RiskDecision

log = logging.getLogger("execution")


class TradeExecutor:
    def __init__(self, broker: PaperBroker, risk: RiskManager, db: Optional[Database] = None):
        self.broker = broker
        self.risk = risk
        self.db = db or get_db()
        self.mode = settings.runtime.mode

    def buy(self, symbol: str, decision: RiskDecision, price: float,
            strategy: str, confidence: float) -> Optional[OrderResult]:
        if not decision.approved:
            self.db.record_order(symbol, "buy", 0, price, "rejected", self.mode,
                                 reason=decision.reason, confidence=confidence)
            return None
        notional = decision.qty * price
        res = self.broker.market_buy(symbol, notional, price)
        self.db.record_order(symbol, "buy", res.qty, price,
                             "filled" if res.ok else "rejected", self.mode,
                             reason=decision.reason, confidence=confidence)
        if res.ok:
            self.db.open_trade(symbol, "buy", res.qty, price, strategy,
                               decision.stop_loss, decision.take_profit)
            log.info("BUY %s qty=%.6f @ %.4f (%s)", symbol, res.qty, price, strategy)
        return res

    def sell(self, symbol: str, qty: float, price: float, reason: str = "signal") -> Optional[OrderResult]:
        res = self.broker.market_sell(symbol, qty, price)
        self.db.record_order(symbol, "sell", qty, price,
                             "filled" if res.ok else "rejected", self.mode, reason=reason)
        if res.ok:
            self._close_trades(symbol, price)
            log.info("SELL %s qty=%.6f @ %.4f (%s)", symbol, res.qty, price, reason)
        return res

    def _close_trades(self, symbol: str, price: float) -> None:
        """Close open trade records for this symbol at the given price."""
        for t in self.db.open_trades():
            if t["symbol"] != symbol:
                continue
            pnl = (price - t["entry_price"]) * t["qty"]
            pnl_pct = (price / t["entry_price"] - 1) if t["entry_price"] else 0.0
            self.db.close_trade(t["id"], price, pnl, pnl_pct)

    def manage_exits(self, prices: Dict[str, float]) -> List[str]:
        """Check open trades for stop/target hits and close them."""
        closed = []
        for t in self.db.open_trades():
            price = prices.get(t["symbol"])
            if price is None:
                continue
            reason = self.risk.check_exit(t["side"], t["entry_price"], price,
                                          t.get("stop_loss"), t.get("take_profit"))
            if reason:
                self.sell(t["symbol"], t["qty"], price, reason=reason)
                closed.append(f"{t['symbol']}:{reason}")
        return closed
