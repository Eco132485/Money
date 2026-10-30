"""
Self-improvement: reviews recent trade history and backtest results, then
re-weights the strategy ensemble toward what is currently working.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from .db import Database, get_db
from .strategy_engine import StrategyEngine

log = logging.getLogger("self_improvement")


class SelfImprover:
    def __init__(self, engine: StrategyEngine, db: Optional[Database] = None):
        self.engine = engine
        self.db = db or get_db()

    def evaluate(self, backtests: Dict[str, Dict]) -> Dict[str, float]:
        """Derive new ensemble weights from backtest metrics (Sharpe + return)."""
        scores = {}
        for name, m in backtests.items():
            if not m or "sharpe" in m and m.get("sharpe") is None:
                scores[name] = 0.1
                continue
            sharpe = float(m.get("sharpe", 0) or 0)
            ret = float(m.get("total_return", 0) or 0)
            dd = abs(float(m.get("max_drawdown", 0) or 0))
            # reward return & sharpe, penalize drawdown
            score = max(0.01, (ret * 2 + sharpe * 0.5) / (1 + dd * 5))
            scores[name] = score
        total = sum(scores.values()) or 1.0
        weights = {k: round(v / total, 3) for k, v in scores.items()}
        self.engine.weights = weights
        log.info("updated strategy weights: %s", weights)
        return weights

    def review_and_update(self, backtests: Dict[str, Dict]) -> Dict[str, float]:
        weights = self.evaluate(backtests)
        self.db.save_strategy(
            name="ensemble",
            params={"weights": weights},
            metrics={k: v for k, v in backtests.items()},
            active=True,
        )
        return weights
