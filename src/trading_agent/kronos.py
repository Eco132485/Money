"""Optional Kronos forecast adapter.

Kronos itself is a Python time-series model, not a universal hosted REST API.
This adapter calls an owner-operated wrapper endpoint documented in docs/AI_INTEGRATIONS.md.
"""
from __future__ import annotations

import logging
import math
import os
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("kronos")


class KronosForecaster:
    def __init__(self):
        self.enabled = os.getenv("KRONOS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.required = os.getenv("KRONOS_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.endpoint = os.getenv("KRONOS_API_URL", "").strip()
        self.api_key = os.getenv("KRONOS_API_KEY", "").strip()
        self.timeout = max(3, min(int(os.getenv("KRONOS_TIMEOUT_SECONDS", "15")), 30))

    def forecast(self, symbol: str, timeframe: str, candles: List[Any]) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        if not self.endpoint:
            return {"available": False, "direction": "unknown", "reason": "Kronos is enabled but KRONOS_API_URL is missing"}
        rows = []
        for candle in candles[-512:]:
            rows.append({
                "timestamp": int(candle.ts),
                "open": float(candle.open),
                "high": float(candle.high),
                "low": float(candle.low),
                "close": float(candle.close),
                "volume": float(getattr(candle, "volume", 0) or 0),
            })
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        try:
            response = requests.post(
                self.endpoint,
                headers=headers,
                json={"symbol": symbol, "timeframe": timeframe, "candles": rows, "pred_len": 3},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            forecast_rows = payload.get("forecast") or payload.get("predictions")
            if not isinstance(forecast_rows, list) or not forecast_rows:
                raise ValueError("Kronos wrapper returned no forecast rows")
            latest = float(rows[-1]["close"])
            predicted = float(forecast_rows[-1]["close"])
            if not math.isfinite(predicted) or predicted <= 0 or latest <= 0:
                raise ValueError("Kronos returned an invalid forecast price")
            change = predicted / latest - 1
            direction = "up" if change > 0.0002 else "down" if change < -0.0002 else "flat"
            return {
                "available": True,
                "direction": direction,
                "last_close": latest,
                "predicted_close": predicted,
                "change_pct": change * 100,
                "model": str(payload.get("model", "Kronos")),
            }
        except Exception as exc:
            log.warning("Kronos forecast failed (%s)", type(exc).__name__)
            return {"available": False, "direction": "unknown", "reason": type(exc).__name__}


kronos_forecaster = KronosForecaster()
