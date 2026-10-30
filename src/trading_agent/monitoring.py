"""
Monitoring & alerting: computes live performance metrics and pushes alerts to
Telegram and/or Discord. All delivery is best-effort and never blocks trading.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import requests

from .config import settings
from .db import Database, get_db

log = logging.getLogger("monitoring")


class Monitor:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()
        self.cfg = settings.notifications

    # ---- metrics ----
    def performance(self) -> Dict[str, float]:
        trades = self.db.closed_trades(limit=1000)
        if not trades:
            return {"num_trades": 0, "win_rate": 0.0, "total_pnl": 0.0,
                    "avg_pnl_pct": 0.0, "profit_factor": 0.0}
        pnls = [t["pnl"] or 0.0 for t in trades]
        pcts = [t["pnl_pct"] or 0.0 for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gross_win = sum(wins)
        gross_loss = -sum(losses)
        return {
            "num_trades": len(trades),
            "win_rate": round(len(wins) / len(trades), 3),
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl_pct": round(sum(pcts) / len(pcts), 4),
            "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else 99.0,
        }

    # ---- alerts ----
    def _send(self, text: str) -> None:
        if not self.cfg.enabled:
            return
        if self.cfg.telegram_token and self.cfg.telegram_chat_id:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{self.cfg.telegram_token}/sendMessage",
                    json={"chat_id": self.cfg.telegram_chat_id, "text": text,
                          "parse_mode": "Markdown"},
                    timeout=10,
                )
            except Exception as exc:
                log.warning("telegram send failed: %s", exc)
        if self.cfg.discord_webhook:
            try:
                requests.post(self.cfg.discord_webhook, json={"content": text}, timeout=10)
            except Exception as exc:
                log.warning("discord send failed: %s", exc)

    def alert(self, text: str) -> None:
        log.info("ALERT: %s", text)
        self.db.log("INFO", "alert", text)
        self._send(text)

    def daily_report(self, equity: float, positions: Dict[str, Dict]) -> str:
        perf = self.performance()
        lines = [
            "*Daily Trading Report*",
            f"Equity: ${equity:,.2f}",
            f"Trades: {perf['num_trades']} | Win rate: {perf['win_rate']:.1%}",
            f"Total PnL: ${perf['total_pnl']:,.2f} | PF: {perf['profit_factor']}",
            f"Open positions: {len(positions)}",
        ]
        text = "\n".join(lines)
        self.alert(text)
        return text
