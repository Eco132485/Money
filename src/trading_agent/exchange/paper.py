"""
Paper-trading broker.

Simulates a spot account: cash balance, long positions, market orders filled
at the current price with a configurable fee. This is the default execution
venue so the agent can run end-to-end without risking real capital.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, Optional

from .base import OrderResult

log = logging.getLogger("paper")


class PaperBroker:
    def __init__(self, initial_balance: float = 10_000.0, fee_rate: float = 0.001):
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self.fee_rate = fee_rate
        # symbol -> {"qty": float, "avg_price": float}
        self.positions: Dict[str, Dict[str, float]] = {}
        self._lock = threading.RLock()

    # ---- valuation ----
    def position_qty(self, symbol: str) -> float:
        with self._lock:
            return self.positions.get(symbol, {}).get("qty", 0.0)

    def equity(self, prices: Dict[str, float]) -> float:
        with self._lock:
            total = self.cash
            for sym, pos in self.positions.items():
                price = prices.get(sym, pos.get("avg_price", 0.0))
                total += pos["qty"] * price
            return total

    def exposure(self, prices: Dict[str, float]) -> float:
        with self._lock:
            total = 0.0
            for sym, pos in self.positions.items():
                price = prices.get(sym, pos.get("avg_price", 0.0))
                total += pos["qty"] * price
            return total

    # ---- orders ----
    def market_buy(self, symbol: str, quote_amount: float, price: float) -> OrderResult:
        """Spend `quote_amount` of cash to buy `symbol` at `price`."""
        with self._lock:
            if price <= 0:
                return OrderResult(False, symbol, "buy", 0, price, "rejected", "invalid price")
            cost = quote_amount
            fee = cost * self.fee_rate
            if cost + fee > self.cash + 1e-9:
                return OrderResult(False, symbol, "buy", 0, price, "rejected", "insufficient cash")
            qty = quote_amount / price
            self.cash -= (cost + fee)
            pos = self.positions.get(symbol, {"qty": 0.0, "avg_price": 0.0})
            new_qty = pos["qty"] + qty
            pos["avg_price"] = ((pos["qty"] * pos["avg_price"]) + (qty * price)) / new_qty if new_qty else 0.0
            pos["qty"] = new_qty
            self.positions[symbol] = pos
            return OrderResult(True, symbol, "buy", qty, price, "filled",
                               f"bought {qty:.6f} @ {price:.4f}")

    def market_sell(self, symbol: str, qty: float, price: float) -> OrderResult:
        with self._lock:
            pos = self.positions.get(symbol)
            if not pos or pos["qty"] <= 0:
                return OrderResult(False, symbol, "sell", 0, price, "rejected", "no position")
            qty = min(qty, pos["qty"])
            proceeds = qty * price
            fee = proceeds * self.fee_rate
            self.cash += (proceeds - fee)
            pos["qty"] -= qty
            if pos["qty"] <= 1e-12:
                self.positions.pop(symbol, None)
            return OrderResult(True, symbol, "sell", qty, price, "filled",
                               f"sold {qty:.6f} @ {price:.4f}")

    def snapshot(self, prices: Dict[str, float]) -> Dict[str, float]:
        with self._lock:
            return {
                "cash": round(self.cash, 2),
                "equity": round(self.equity(prices), 2),
                "exposure": round(self.exposure(prices), 2),
                "positions": {s: {"qty": round(p["qty"], 8), "avg_price": round(p["avg_price"], 4)}
                              for s, p in self.positions.items()},
            }
