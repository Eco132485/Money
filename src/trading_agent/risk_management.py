"""
Risk management: position sizing, stop/target, daily loss limit, max drawdown
and a kill switch. Every order must pass `pre_trade_check` before execution.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from .config import RiskConfig, settings

log = logging.getLogger("risk")


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    qty: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_amount: float = 0.0


class RiskManager:
    def __init__(self, cfg: Optional[RiskConfig] = None):
        self.cfg = cfg or settings.risk
        self.killed = False
        self.kill_reason = ""

    # ---- kill switch ----
    def trigger_kill_switch(self, reason: str) -> None:
        self.killed = True
        self.kill_reason = reason
        log.critical("KILL SWITCH: %s", reason)

    def reset_kill_switch(self) -> None:
        self.killed = False
        self.kill_reason = ""

    # ---- sizing ----
    def position_size(self, equity: float, price: float, stop_loss: float) -> float:
        """Risk-based sizing: risk a fixed % of equity between entry and stop."""
        if price <= 0:
            return 0.0
        risk_per_unit = abs(price - stop_loss)
        if risk_per_unit <= 0:
            risk_per_unit = price * self.cfg.stop_loss_pct
        risk_amount = equity * self.cfg.risk_per_trade_pct
        qty = risk_amount / risk_per_unit
        # cap by max position % of equity
        max_notional = equity * self.cfg.max_position_pct
        qty = min(qty, max_notional / price)
        return max(qty, 0.0)

    # ---- pre-trade gate ----
    def pre_trade_check(self, *, equity: float, price: float, confidence: float,
                        current_exposure: float, open_positions: int,
                        day_start_equity: Optional[float], peak_equity: float,
                        stop_loss: Optional[float] = None,
                        take_profit: Optional[float] = None) -> RiskDecision:
        if self.killed:
            return RiskDecision(False, f"kill switch active: {self.kill_reason}")

        if confidence < self.cfg.min_confidence:
            return RiskDecision(False, f"confidence {confidence:.2f} < min {self.cfg.min_confidence}")

        if open_positions >= self.cfg.max_open_positions:
            return RiskDecision(False, f"max open positions ({self.cfg.max_open_positions}) reached")

        # daily loss limit
        if day_start_equity and day_start_equity > 0:
            day_pnl_pct = (equity - day_start_equity) / day_start_equity
            if day_pnl_pct <= -self.cfg.max_daily_loss_pct:
                self.trigger_kill_switch(f"daily loss limit hit ({day_pnl_pct:.2%})")
                return RiskDecision(False, "daily loss limit reached")

        # max drawdown
        if peak_equity > 0:
            dd = (peak_equity - equity) / peak_equity
            if dd >= self.cfg.max_drawdown_pct:
                self.trigger_kill_switch(f"max drawdown hit ({dd:.2%})")
                return RiskDecision(False, "max drawdown reached")

        # portfolio exposure cap
        if equity > 0 and current_exposure / equity >= self.cfg.max_portfolio_exposure_pct:
            return RiskDecision(False, "portfolio exposure cap reached")

        sl = stop_loss if stop_loss else price * (1 - self.cfg.stop_loss_pct)
        tp = take_profit if take_profit else price * (1 + self.cfg.take_profit_pct)
        qty = self.position_size(equity, price, sl)
        if qty <= 0:
            return RiskDecision(False, "computed size is zero")

        notional = qty * price
        if notional > equity * self.cfg.max_position_pct * 1.001:
            return RiskDecision(False, "position exceeds max position size")

        risk_amount = qty * abs(price - sl)
        return RiskDecision(True, "approved", qty=qty, stop_loss=sl,
                            take_profit=tp, risk_amount=risk_amount)

    # ---- exit checks ----
    def check_exit(self, side: str, entry: float, price: float,
                   stop_loss: Optional[float], take_profit: Optional[float]) -> Optional[str]:
        if side == "buy":
            if stop_loss and price <= stop_loss:
                return "stop_loss"
            if take_profit and price >= take_profit:
                return "take_profit"
        else:  # short (not used in spot, kept for futures)
            if stop_loss and price >= stop_loss:
                return "stop_loss"
            if take_profit and price <= take_profit:
                return "take_profit"
        return None
