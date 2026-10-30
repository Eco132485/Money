"""Exchange abstractions: market data interface and shared types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Ticker:
    symbol: str
    price: float
    change_pct_24h: float
    volume_24h: float
    high_24h: float
    low_24h: float


@dataclass
class OrderResult:
    ok: bool
    symbol: str
    side: str
    qty: float
    price: float
    status: str
    message: str = ""
    order_id: Optional[int] = None


class MarketDataProvider:
    """Interface implemented by concrete exchange adapters."""

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> List[Candle]:
        raise NotImplementedError

    def get_ticker(self, symbol: str) -> Ticker:
        raise NotImplementedError
