"""Binance public market-data adapter (no API key required for read-only data)."""
from __future__ import annotations

import logging
from typing import List

import requests

from .base import Candle, MarketDataProvider, Ticker
from ..config import settings

log = logging.getLogger("binance")

_INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}


class BinanceMarketData(MarketDataProvider):
    def __init__(self, base_url: str | None = None, timeout: int = 15):
        self.base_url = (base_url or settings.exchange.base_url).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> List[Candle]:
        resp = self.session.get(
            f"{self.base_url}/api/v3/klines",
            params={"symbol": symbol.upper(), "interval": interval, "limit": limit},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        candles = []
        for k in resp.json():
            candles.append(Candle(
                ts=int(k[0]),
                open=float(k[1]), high=float(k[2]), low=float(k[3]),
                close=float(k[4]), volume=float(k[5]),
            ))
        return candles

    def get_ticker(self, symbol: str) -> Ticker:
        resp = self.session.get(
            f"{self.base_url}/api/v3/ticker/24hr",
            params={"symbol": symbol.upper()},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        d = resp.json()
        return Ticker(
            symbol=d["symbol"],
            price=float(d["lastPrice"]),
            change_pct_24h=float(d["priceChangePercent"]),
            volume_24h=float(d["volume"]),
            high_24h=float(d["highPrice"]),
            low_24h=float(d["lowPrice"]),
        )


class BybitMarketData(MarketDataProvider):
    """Bybit v5 public market data adapter."""

    def __init__(self, base_url: str = "https://api.bybit.com", timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def get_klines(self, symbol: str, interval: str = "60", limit: int = 500) -> List[Candle]:
        resp = self.session.get(
            f"{self.base_url}/v5/market/kline",
            params={"category": "spot", "symbol": symbol.upper(), "interval": interval, "limit": limit},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        rows = resp.json()["result"]["list"]
        # Bybit returns newest first
        candles = [
            Candle(ts=int(r[0]), open=float(r[1]), high=float(r[2]),
                   low=float(r[3]), close=float(r[4]), volume=float(r[5]))
            for r in reversed(rows)
        ]
        return candles

    def get_ticker(self, symbol: str) -> Ticker:
        resp = self.session.get(
            f"{self.base_url}/v5/market/tickers",
            params={"category": "spot", "symbol": symbol.upper()},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        d = resp.json()["result"]["list"][0]
        price = float(d["lastPrice"])
        prev = float(d.get("prevPrice24h", price)) or price
        return Ticker(
            symbol=d["symbol"], price=price,
            change_pct_24h=(price - prev) / prev * 100 if prev else 0.0,
            volume_24h=float(d.get("volume24h", 0)),
            high_24h=float(d.get("highPrice24h", price)),
            low_24h=float(d.get("lowPrice24h", price)),
        )


class KrakenMarketData(MarketDataProvider):
    """Kraken public OHLC adapter. Maps BTCUSDT->XBTUSD, ETHUSDT->ETHUSD."""

    _PAIR = {"BTCUSDT": "XBTUSD", "ETHUSDT": "ETHUSD", "SOLUSDT": "SOLUSD"}
    _INTERVAL = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}

    def __init__(self, base_url: str = "https://api.kraken.com", timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _pair(self, symbol: str) -> str:
        return self._PAIR.get(symbol.upper(), symbol.upper())

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> List[Candle]:
        pair = self._pair(symbol)
        iv = self._INTERVAL.get(interval, 60)
        resp = self.session.get(
            f"{self.base_url}/0/public/OHLC",
            params={"pair": pair, "interval": iv},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()["result"]
        rows = next(v for k, v in data.items() if k != "last")
        candles = [Candle(ts=int(r[0]) * 1000, open=float(r[1]), high=float(r[2]),
                          low=float(r[3]), close=float(r[4]), volume=float(r[6]))
                   for r in rows]
        return candles[-limit:]

    def get_ticker(self, symbol: str) -> Ticker:
        pair = self._pair(symbol)
        resp = self.session.get(f"{self.base_url}/0/public/Ticker", params={"pair": pair}, timeout=self.timeout)
        resp.raise_for_status()
        d = next(v for k, v in resp.json()["result"].items() if k != "last")
        price = float(d["c"][0])
        return Ticker(symbol=symbol, price=price, change_pct_24h=0.0,
                      volume_24h=float(d["v"][1]), high_24h=float(d["h"][1]), low_24h=float(d["l"][1]))


class CoinbaseMarketData(MarketDataProvider):
    """Coinbase Exchange public candles adapter."""

    _PRODUCT = {"BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD", "SOLUSDT": "SOL-USD"}
    _GRAN = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400}

    def __init__(self, base_url: str = "https://api.exchange.coinbase.com", timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _product(self, symbol: str) -> str:
        return self._PRODUCT.get(symbol.upper(), symbol.upper().replace("USDT", "-USD"))

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 300) -> List[Candle]:
        product = self._product(symbol)
        gran = self._GRAN.get(interval, 3600)
        resp = self.session.get(
            f"{self.base_url}/products/{product}/candles",
            params={"granularity": gran},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        rows = resp.json()  # [time, low, high, open, close, volume], newest first
        candles = [Candle(ts=int(r[0]) * 1000, open=float(r[3]), high=float(r[2]),
                          low=float(r[1]), close=float(r[4]), volume=float(r[5]))
                   for r in reversed(rows)]
        return candles[-limit:]

    def get_ticker(self, symbol: str) -> Ticker:
        product = self._product(symbol)
        resp = self.session.get(f"{self.base_url}/products/{product}/ticker", timeout=self.timeout)
        resp.raise_for_status()
        d = resp.json()
        return Ticker(symbol=symbol, price=float(d["price"]), change_pct_24h=0.0,
                      volume_24h=float(d.get("volume", 0)), high_24h=float(d["price"]), low_24h=float(d["price"]))


def get_market_data() -> MarketDataProvider:
    name = settings.exchange.name.lower()
    if name == "bybit":
        return BybitMarketData()
    if name == "kraken":
        return KrakenMarketData()
    if name == "coinbase":
        return CoinbaseMarketData()
    if name == "binanceus":
        return BinanceMarketData(base_url="https://api.binance.us")
    return BinanceMarketData()
