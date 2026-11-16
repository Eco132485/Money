"""Free, read-only Yahoo Finance FX market-data adapter.

Uses the public chart endpoint without credentials. It is best-effort public
data, not an exchange execution API. Stale or missing data must stop trading.
"""
from __future__ import annotations

from typing import List
import requests

from .base import Candle, MarketDataProvider, Ticker

_INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
              "1h": "1h", "4h": "1h", "1d": "1d"}
_RANGES = {"1m": "1d", "5m": "5d", "15m": "5d", "30m": "1mo",
           "1h": "1mo", "4h": "3mo", "1d": "1y"}


class YahooForexMarketData(MarketDataProvider):
    """Read-only FX quotes and candles from Yahoo Finance's public chart API."""
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 ISA-Paper-Trader/1.0"})

    @staticmethod
    def _ticker(symbol: str) -> str:
        pair = symbol.upper().replace("FX:", "").replace("/", "").replace("-", "")
        if len(pair) != 6 or not pair.isalpha():
            raise ValueError(f"Unsupported FX pair: {symbol}")
        return pair + "=X"

    def _chart(self, symbol: str, interval: str):
        ticker = self._ticker(symbol)
        iv = _INTERVALS.get(interval)
        if not iv:
            raise ValueError(f"Unsupported FX timeframe: {interval}")
        response = self.session.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"range": _RANGES[interval], "interval": iv},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()["chart"]
        if payload.get("error") or not payload.get("result"):
            raise RuntimeError(f"FX data unavailable for {symbol}")
        return payload["result"][0]

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 300) -> List[Candle]:
        result = self._chart(symbol, interval)
        timestamps = result.get("timestamp") or []
        quote = result["indicators"]["quote"][0]
        candles = []
        for i, ts in enumerate(timestamps):
            values = [quote.get(k, [None] * len(timestamps))[i]
                      for k in ("open", "high", "low", "close", "volume")]
            if any(v is None for v in values[:4]):
                continue
            candles.append(Candle(
                ts=int(ts) * 1000, open=float(values[0]), high=float(values[1]),
                low=float(values[2]), close=float(values[3]),
                volume=float(values[4] or 0),
            ))
        return candles[-limit:]

    def get_ticker(self, symbol: str) -> Ticker:
        result = self._chart(symbol, "1h")
        meta = result.get("meta", {})
        price = float(meta.get("regularMarketPrice") or 0)
        if price <= 0:
            raise RuntimeError(f"No valid FX quote for {symbol}")
        previous = float(meta.get("chartPreviousClose") or price)
        return Ticker(
            symbol=symbol.upper(), price=price,
            change_pct_24h=((price / previous) - 1) * 100 if previous else 0.0,
            volume_24h=0.0, high_24h=float(meta.get("regularMarketDayHigh") or price),
            low_24h=float(meta.get("regularMarketDayLow") or price),
        )
