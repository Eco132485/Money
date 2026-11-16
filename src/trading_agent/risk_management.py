"""Server-side shared portfolio risk controls for Forex and crypto."""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional
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

    def trigger_kill_switch(self, reason: str) -> None:
        self.killed, self.kill_reason = True, reason
        log.critical("KILL SWITCH: %s", reason)

    def reset_kill_switch(self) -> None:
        self.killed, self.kill_reason = False, ""

    def position_size(self, equity: float, price: float, stop_loss: float,
                      current_exposure: float = 0.0) -> float:
        if equity <= 0 or price <= 0:
            return 0.0
        risk_per_unit = abs(price - stop_loss)
        if risk_per_unit <= 0:
            risk_per_unit = price * self.cfg.stop_loss_pct
        risk_amount = equity * self.cfg.risk_per_trade_pct
        qty = risk_amount / risk_per_unit
        max_trade_notional = equity * self.cfg.max_position_pct
        exposure_room = max(0.0, equity * self.cfg.max_portfolio_exposure_pct - current_exposure)
        qty = min(qty, max_trade_notional / price, exposure_room / price)
        return max(qty, 0.0)

    def pre_trade_check(self, *, equity: float, price: float, confidence: float,
                        current_exposure: float, open_positions: int,
                        day_start_equity: Optional[float], peak_equity: float,
                        stop_loss: Optional[float] = None,
                        take_profit: Optional[float] = None,
                        side: str = "buy") -> RiskDecision:
        if self.killed:
            return RiskDecision(False, f"kill switch active: {self.kill_reason}")
        if equity <= 0 or price <= 0:
            return RiskDecision(False, "invalid or depleted virtual equity")
        if confidence < self.cfg.min_confidence:
            return RiskDecision(False, f"confidence {confidence:.2f} < min {self.cfg.min_confidence}")
        if open_positions >= self.cfg.max_open_positions:
            return RiskDecision(False, f"max open positions ({self.cfg.max_open_positions}) reached")
        if day_start_equity and day_start_equity > 0:
            loss = (equity - day_start_equity) / day_start_equity
            if loss <= -self.cfg.max_daily_loss_pct:
                self.trigger_kill_switch(f"daily loss limit hit ({loss:.2%})")
                return RiskDecision(False, "daily loss limit reached")
        if peak_equity > 0:
            drawdown = (peak_equity - equity) / peak_equity
            if drawdown >= self.cfg.max_drawdown_pct:
                self.trigger_kill_switch(f"max drawdown hit ({drawdown:.2%})")
                return RiskDecision(False, "max drawdown reached")
        exposure_cap = equity * self.cfg.max_portfolio_exposure_pct
        if current_exposure >= exposure_cap - 1e-9:
            return RiskDecision(False, "shared Forex+crypto exposure cap reached")
        if side not in {"buy", "sell"}:
            return RiskDecision(False, "invalid trade direction")
        sl = stop_loss if stop_loss is not None else price * (1 - self.cfg.stop_loss_pct if side == "buy" else 1 + self.cfg.stop_loss_pct)
        tp = take_profit if take_profit is not None else price * (1 + self.cfg.take_profit_pct if side == "buy" else 1 - self.cfg.take_profit_pct)
        if sl <= 0 or sl == price:
            return RiskDecision(False, "invalid stop-loss")
        qty = self.position_size(equity, price, sl, current_exposure)
        if qty <= 0:
            return RiskDecision(False, "no remaining portfolio exposure capacity")
        notional = qty * price
        risk_amount = qty * abs(price - sl)
        if risk_amount > equity * self.cfg.risk_per_trade_pct + 1e-8:
            return RiskDecision(False, "per-trade risk exceeds 1% cap")
        if current_exposure + notional > exposure_cap + 1e-8:
            return RiskDecision(False, "projected shared exposure exceeds 30% cap")
        return RiskDecision(True, "approved", qty, sl, tp, risk_amount)

    def check_exit(self, side: str, entry: float, price: float,
                   stop_loss: Optional[float], take_profit: Optional[float]) -> Optional[str]:
        if side == "buy":
            if stop_loss and price <= stop_loss: return "stop_loss"
            if take_profit and price >= take_profit: return "take_profit"
        else:
            if stop_loss and price >= stop_loss: return "stop_loss"
            if take_profit and price <= take_profit: return "take_profit"
        return None
