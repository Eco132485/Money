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
    def __init__(self, initial_balance: float = 1000.0, fee_rate: float = 0.001, state_store=None):
        self.initial_balance = initial_balance
        self.fee_rate = fee_rate
        self.state_store = state_store
        self._lock = threading.RLock()
        saved = state_store.load_paper_state() if state_store is not None else None
        self.cash = float(saved.get("cash", initial_balance)) if saved else initial_balance
        self.positions: Dict[str, Dict[str, float]] = (
            {k: {"qty": float(v["qty"]), "avg_price": float(v["avg_price"]),
                  "side": v.get("side", "long"), "margin": float(v.get("margin", 0.0))}
             for k, v in saved.get("positions", {}).items()}
            if saved else {}
        )
        if state_store is not None and saved is None:
            self._persist()

    def _persist(self) -> None:
        if self.state_store is not None:
            self.state_store.save_paper_state({
                "cash": self.cash,
                "positions": self.positions,
                "initial_balance": self.initial_balance,
            })

    # ---- valuation ----
    def position_qty(self, symbol: str) -> float:
        with self._lock:
            return self.positions.get(symbol, {}).get("qty", 0.0)

    def position_side(self, symbol: str) -> Optional[str]:
        with self._lock:
            pos = self.positions.get(symbol)
            return pos.get("side", "long") if pos else None

    def equity(self, prices: Dict[str, float]) -> float:
        with self._lock:
            total = self.cash
            for sym, pos in self.positions.items():
                price = prices.get(sym, pos.get("avg_price", 0.0))
                if pos.get("side", "long") == "short":
                    total += pos.get("margin", 0.0) + (pos["avg_price"] - price) * pos["qty"]
                else:
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
            pos = self.positions.get(symbol, {"qty": 0.0, "avg_price": 0.0, "side": "long", "margin": 0.0})
            if pos.get("side", "long") != "long":
                return OrderResult(False, symbol, "buy", 0, price, "rejected", "short position must be covered first")
            cost = quote_amount
            fee = cost * self.fee_rate
            if cost + fee > self.cash + 1e-9:
                return OrderResult(False, symbol, "buy", 0, price, "rejected", "insufficient cash")
            qty = quote_amount / price
            self.cash -= (cost + fee)
            new_qty = pos["qty"] + qty
            pos["avg_price"] = ((pos["qty"] * pos["avg_price"]) + (qty * price)) / new_qty if new_qty else 0.0
            pos["qty"] = new_qty
            pos["side"] = "long"
            self.positions[symbol] = pos
            self._persist()
            return OrderResult(True, symbol, "buy", qty, price, "filled",
                               f"bought {qty:.6f} @ {price:.4f}")

    def market_sell(self, symbol: str, qty: float, price: float) -> OrderResult:
        with self._lock:
            pos = self.positions.get(symbol)
            if not pos or pos["qty"] <= 0 or pos.get("side", "long") != "long":
                return OrderResult(False, symbol, "sell", 0, price, "rejected", "no long position")
            qty = min(qty, pos["qty"])
            proceeds = qty * price
            fee = proceeds * self.fee_rate
            self.cash += (proceeds - fee)
            pos["qty"] -= qty
            if pos["qty"] <= 1e-12:
                self.positions.pop(symbol, None)
            self._persist()
            return OrderResult(True, symbol, "sell", qty, price, "filled",
                               f"sold {qty:.6f} @ {price:.4f}")

    def market_short(self, symbol: str, quote_amount: float, price: float) -> OrderResult:
        """Open an unleveraged simulated short using quote_amount as locked margin."""
        with self._lock:
            if price <= 0 or quote_amount <= 0:
                return OrderResult(False, symbol, "sell", 0, price, "rejected", "invalid short size or price")
            if symbol in self.positions:
                return OrderResult(False, symbol, "sell", 0, price, "rejected", "position already exists")
            fee = quote_amount * self.fee_rate
            if quote_amount + fee > self.cash + 1e-9:
                return OrderResult(False, symbol, "sell", 0, price, "rejected", "insufficient cash for short margin")
            qty = quote_amount / price
            self.cash -= quote_amount + fee
            self.positions[symbol] = {
                "qty": qty, "avg_price": price, "side": "short", "margin": quote_amount
            }
            self._persist()
            return OrderResult(True, symbol, "sell", qty, price, "filled",
                               f"shorted {qty:.6f} @ {price:.6f}")

    def market_cover(self, symbol: str, qty: float, price: float) -> OrderResult:
        """Close a simulated short and release proportional margin plus P/L."""
        with self._lock:
            pos = self.positions.get(symbol)
            if not pos or pos.get("side") != "short" or price <= 0:
                return OrderResult(False, symbol, "buy", 0, price, "rejected", "no short position or invalid price")
            qty = min(max(qty, 0.0), pos["qty"])
            if qty <= 0:
                return OrderResult(False, symbol, "buy", 0, price, "rejected", "invalid cover quantity")
            old_qty = pos["qty"]
            margin_release = pos.get("margin", 0.0) * qty / old_qty
            pnl = (pos["avg_price"] - price) * qty
            fee = qty * price * self.fee_rate
            self.cash += margin_release + pnl - fee
            pos["qty"] -= qty
            pos["margin"] = max(0.0, pos.get("margin", 0.0) - margin_release)
            if pos["qty"] <= 1e-12:
                self.positions.pop(symbol, None)
            self._persist()
            return OrderResult(True, symbol, "buy", qty, price, "filled",
                               f"covered {qty:.6f} @ {price:.6f}")

    def snapshot(self, prices: Dict[str, float]) -> Dict[str, float]:
        with self._lock:
            return {
                "cash": round(self.cash, 2),
                "equity": round(self.equity(prices), 2),
                "exposure": round(self.exposure(prices), 2),
                "positions": {s: {"qty": round(p["qty"], 8), "avg_price": round(p["avg_price"], 6),
                                  "side": p.get("side", "long"), "margin": round(p.get("margin", 0.0), 6)}
                              for s, p in self.positions.items()},
            }
