import pandas as pd

from trading_agent.market_analysis import (
    candles_to_df, ema, sma, rsi, macd, atr, bollinger, adx, analyze,
)


def test_ema_matches_manual():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    out = ema(s, 3)
    assert len(out) == 5
    assert out.iloc[-1] > out.iloc[0]


def test_rsi_bounds(uptrend_candles):
    df = candles_to_df(uptrend_candles)
    r = rsi(df["close"])
    assert r.min() >= 0 and r.max() <= 100


def test_atr_positive(uptrend_candles):
    df = candles_to_df(uptrend_candles)
    assert (atr(df).dropna() > 0).all()


def test_bollinger_order(uptrend_candles):
    df = candles_to_df(uptrend_candles)
    lower, mid, upper = bollinger(df["close"])
    valid = lower.notna() & upper.notna()
    assert (lower[valid] <= mid[valid]).all()
    assert (mid[valid] <= upper[valid]).all()


def test_analyze_returns_view(uptrend_candles):
    view = analyze(uptrend_candles, "TESTUSDT")
    assert view.price > 0
    assert view.trend in {"up", "down", "sideways"}
    assert view.regime in {"trending", "ranging", "volatile"}
    assert view.support <= view.price <= view.resistance * 1.5
