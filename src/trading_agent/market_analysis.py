"""
Market analysis: turns raw candles into a structured market view —
trend, momentum, volatility, regime and key support/resistance levels.
Pure pandas/numpy so it is deterministic and unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List

import numpy as np
import pandas as pd

from .exchange.base import Candle


def candles_to_df(candles: List[Candle]) -> pd.DataFrame:
    df = pd.DataFrame([asdict(c) for c in candles])
    if df.empty:
        return df
    df = df.sort_values("ts").reset_index(drop=True)
    return df


# ---------- indicators ----------
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def bollinger(series: pd.Series, period: int = 20, num_std: float = 2.0):
    mid = sma(series, period)
    std = series.rolling(period).std()
    return mid - num_std * std, mid, mid + num_std * std


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_ = tr.rolling(period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(period).mean() / atr_.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(period).mean() / atr_.replace(0, np.nan)
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    return dx.rolling(period).mean().fillna(0)


@dataclass
class MarketView:
    symbol: str
    price: float
    trend: str            # up | down | sideways
    regime: str           # trending | ranging | volatile
    rsi: float
    macd_hist: float
    atr_pct: float
    adx: float
    ema_fast: float
    ema_slow: float
    bb_upper: float
    bb_lower: float
    support: float
    resistance: float
    change_pct: float
    volatility: float

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


def analyze(candles: List[Candle], symbol: str = "") -> MarketView:
    df = candles_to_df(candles)
    if len(df) < 30:
        raise ValueError("need at least 30 candles for analysis")

    close = df["close"]
    price = float(close.iloc[-1])

    ema_fast = float(ema(close, 12).iloc[-1])
    ema_slow = float(ema(close, 26).iloc[-1])
    rsi_val = float(rsi(close).iloc[-1])
    _, _, hist = macd(close)
    macd_hist = float(hist.iloc[-1])
    atr_series = atr(df)
    atr_val = float(atr_series.iloc[-1])
    atr_pct = atr_val / price if price else 0.0
    adx_val = float(adx(df).iloc[-1])
    bb_lower, bb_mid, bb_upper = bollinger(close)
    bb_lower_v, bb_upper_v = float(bb_lower.iloc[-1]), float(bb_upper.iloc[-1])

    # trend from EMA stack + slope
    slope = float(ema(close, 12).iloc[-1] - ema(close, 12).iloc[-5])
    if ema_fast > ema_slow and slope > 0:
        trend = "up"
    elif ema_fast < ema_slow and slope < 0:
        trend = "down"
    else:
        trend = "sideways"

    # volatility regime
    volatility = float(close.pct_change().tail(50).std() * np.sqrt(24 * 365) if len(close) > 50 else close.pct_change().std())
    if atr_pct > 0.03:
        regime = "volatile"
    elif adx_val > 25:
        regime = "trending"
    else:
        regime = "ranging"

    # key levels: recent swing high/low + round-number proximity
    recent = df.tail(100)
    resistance = float(recent["high"].max())
    support = float(recent["low"].min())
    change_pct = float((price / close.iloc[-24] - 1) * 100) if len(close) > 24 else 0.0

    return MarketView(
        symbol=symbol, price=price, trend=trend, regime=regime,
        rsi=rsi_val, macd_hist=macd_hist, atr_pct=atr_pct, adx=adx_val,
        ema_fast=ema_fast, ema_slow=ema_slow,
        bb_upper=bb_upper_v, bb_lower=bb_lower_v,
        support=support, resistance=resistance,
        change_pct=change_pct, volatility=volatility,
    )
