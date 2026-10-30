"""
Strategy engine: signal generation + vectorized backtesting.

Strategies:
  * TrendFollow  — EMA cross + ADX filter
  * MeanReversion — RSI + Bollinger bands
  * Breakout      — Donchian channel breakout with ATR stops

Each strategy returns a Signal(action, confidence, rationale, stop, target).
The backtester simulates the strategy over historical candles and reports
return, Sharpe, max drawdown, win rate and profit factor.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .exchange.base import Candle
from .market_analysis import (
    candles_to_df, ema, rsi, atr, bollinger, adx,
)


@dataclass
class Signal:
    action: str          # buy | sell | hold
    confidence: float
    rationale: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


class BaseStrategy:
    name = "base"

    def generate(self, df: pd.DataFrame, i: int = -1) -> Signal:
        raise NotImplementedError

    def backtest(self, df: pd.DataFrame, fee: float = 0.001) -> Dict[str, float]:
        """Simple long/flat backtest driven by per-bar signals."""
        if len(df) < 50:
            return {"error": "insufficient data"}
        equity = 1.0
        position = 0.0
        entry = 0.0
        curve = []
        trades = []
        for i in range(1, len(df)):
            window = df.iloc[: i + 1]
            sig = self.generate(window, -1)
            price = float(df["close"].iloc[i])
            if sig.action == "buy" and position == 0.0:
                position = equity / price
                entry = price
                equity -= equity * fee
            elif sig.action == "sell" and position > 0.0:
                equity = position * price
                equity -= equity * fee
                pnl = (price / entry - 1) if entry else 0.0
                trades.append(pnl)
                position = 0.0
            curve.append(equity if position == 0.0 else position * price)
        if position > 0.0:
            price = float(df["close"].iloc[-1])
            equity = position * price
            trades.append(price / entry - 1 if entry else 0.0)
        curve.append(equity)
        return self._metrics(np.array(curve), np.array(trades))

    @staticmethod
    def _metrics(curve: np.ndarray, trades: np.ndarray) -> Dict[str, float]:
        if len(curve) < 2:
            return {"error": "no curve"}
        rets = np.diff(curve) / curve[:-1]
        total_return = float(curve[-1] / curve[0] - 1)
        ann = 24 * 365
        sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(ann)) if np.std(rets) > 0 else 0.0
        peak = np.maximum.accumulate(curve)
        dd = (curve - peak) / peak
        max_dd = float(dd.min())
        wins = trades[trades > 0]
        losses = trades[trades < 0]
        win_rate = float(len(wins) / len(trades)) if len(trades) else 0.0
        gross_win = float(wins.sum()) if len(wins) else 0.0
        gross_loss = float(-losses.sum()) if len(losses) else 0.0
        profit_factor = float(gross_win / gross_loss) if gross_loss > 0 else float("inf")
        return {
            "total_return": round(total_return, 4),
            "sharpe": round(sharpe, 3),
            "max_drawdown": round(max_dd, 4),
            "win_rate": round(win_rate, 3),
            "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else 99.0,
            "num_trades": int(len(trades)),
        }


class TrendFollow(BaseStrategy):
    name = "trend_follow"

    def generate(self, df: pd.DataFrame, i: int = -1) -> Signal:
        close = df["close"]
        fast = ema(close, 12)
        slow = ema(close, 26)
        adx_val = float(adx(df).iloc[i])
        price = float(close.iloc[i])
        atr_val = float(atr(df).iloc[i]) or price * 0.01
        crossed_up = fast.iloc[i] > slow.iloc[i] and fast.iloc[i - 1] <= slow.iloc[i - 1]
        crossed_dn = fast.iloc[i] < slow.iloc[i] and fast.iloc[i - 1] >= slow.iloc[i - 1]
        if crossed_up and adx_val > 20:
            conf = min(0.9, 0.5 + adx_val / 100)
            return Signal("buy", conf, f"EMA bullish cross, ADX={adx_val:.1f}",
                          stop_loss=price - 1.5 * atr_val, take_profit=price + 3 * atr_val,
                          strategy=self.name)
        if crossed_dn and adx_val > 20:
            conf = min(0.9, 0.5 + adx_val / 100)
            return Signal("sell", conf, f"EMA bearish cross, ADX={adx_val:.1f}",
                          stop_loss=price + 1.5 * atr_val, take_profit=price - 3 * atr_val,
                          strategy=self.name)
        return Signal("hold", 0.0, "no cross", strategy=self.name)


class MeanReversion(BaseStrategy):
    name = "mean_reversion"

    def generate(self, df: pd.DataFrame, i: int = -1) -> Signal:
        close = df["close"]
        r = rsi(close)
        lower, mid, upper = bollinger(close)
        price = float(close.iloc[i])
        atr_val = float(atr(df).iloc[i]) or price * 0.01
        if r.iloc[i] < 30 and price <= lower.iloc[i]:
            conf = min(0.9, 0.5 + (30 - float(r.iloc[i])) / 100)
            return Signal("buy", conf, f"Oversold RSI={r.iloc[i]:.1f}, below lower BB",
                          stop_loss=price - 1.5 * atr_val, take_profit=float(mid.iloc[i]),
                          strategy=self.name)
        if r.iloc[i] > 70 and price >= upper.iloc[i]:
            conf = min(0.9, 0.5 + (float(r.iloc[i]) - 70) / 100)
            return Signal("sell", conf, f"Overbought RSI={r.iloc[i]:.1f}, above upper BB",
                          stop_loss=price + 1.5 * atr_val, take_profit=float(mid.iloc[i]),
                          strategy=self.name)
        return Signal("hold", 0.0, "within bands", strategy=self.name)


class Breakout(BaseStrategy):
    name = "breakout"

    def generate(self, df: pd.DataFrame, i: int = -1, lookback: int = 20) -> Signal:
        if len(df) < lookback + 2:
            return Signal("hold", 0.0, "insufficient", strategy=self.name)
        price = float(df["close"].iloc[i])
        hi = float(df["high"].iloc[i - lookback:i].max())
        lo = float(df["low"].iloc[i - lookback:i].min())
        atr_val = float(atr(df).iloc[i]) or price * 0.01
        if price > hi:
            return Signal("buy", 0.65, f"Breakout above {hi:.2f}",
                          stop_loss=price - 1.5 * atr_val, take_profit=price + 3 * atr_val,
                          strategy=self.name)
        if price < lo:
            return Signal("sell", 0.65, f"Breakdown below {lo:.2f}",
                          stop_loss=price + 1.5 * atr_val, take_profit=price - 3 * atr_val,
                          strategy=self.name)
        return Signal("hold", 0.0, "inside channel", strategy=self.name)


STRATEGIES = {
    "trend_follow": TrendFollow,
    "mean_reversion": MeanReversion,
    "breakout": Breakout,
}


class StrategyEngine:
    """Combines signals from all strategies with a confidence-weighted vote."""

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.strategies = {name: cls() for name, cls in STRATEGIES.items()}
        self.weights = weights or {name: 1.0 for name in STRATEGIES}

    def generate(self, df: pd.DataFrame) -> Signal:
        votes = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
        details = []
        for name, strat in self.strategies.items():
            try:
                sig = strat.generate(df)
            except Exception:
                continue
            w = self.weights.get(name, 1.0)
            votes[sig.action] += sig.confidence * w
            details.append({"strategy": name, "action": sig.action, "confidence": round(sig.confidence, 3)})
        action = max(votes, key=votes.get)
        total = sum(votes.values())
        # No conviction at all -> hold (avoids defaulting to "buy" at 0 conf)
        if total <= 1e-9 or votes[action] <= 1e-9:
            action = "hold"
        confidence = (votes[action] / total) if (action != "hold" and total > 0) else 0.0
        # pick stop/target from the strongest non-hold strategy
        best = None
        for name, strat in self.strategies.items():
            try:
                s = strat.generate(df)
            except Exception:
                continue
            if s.action == action and action != "hold":
                if best is None or s.confidence > best.confidence:
                    best = s
        return Signal(
            action=action,
            confidence=round(confidence, 3),
            rationale="; ".join(f"{d['strategy']}:{d['action']}({d['confidence']})" for d in details),
            stop_loss=best.stop_loss if best else None,
            take_profit=best.take_profit if best else None,
            strategy=best.strategy if best else "ensemble",
        )

    def backtest_all(self, df: pd.DataFrame, fee: float = 0.001) -> Dict[str, Dict]:
        results = {}
        for name, strat in self.strategies.items():
            results[name] = strat.backtest(df, fee=fee)
        return results


def backtest_candles(candles: List[Candle], fee: float = 0.001) -> Dict[str, Dict]:
    df = candles_to_df(candles)
    return StrategyEngine().backtest_all(df, fee=fee)
