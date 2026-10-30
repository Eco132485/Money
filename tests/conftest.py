"""Shared fixtures: synthetic OHLCV candles."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_agent.exchange.base import Candle  # noqa: E402


def make_candles(n: int = 300, start: float = 100.0, drift: float = 0.0005,
                 vol: float = 0.01, seed: int = 42):
    rng = np.random.default_rng(seed)
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + drift + rng.normal(0, vol)))
    candles = []
    for i, p in enumerate(prices):
        o = p * (1 + rng.normal(0, vol / 3))
        h = max(o, p) * (1 + abs(rng.normal(0, vol / 2)))
        l = min(o, p) * (1 - abs(rng.normal(0, vol / 2)))
        candles.append(Candle(ts=1_600_000_000_000 + i * 3_600_000,
                              open=o, high=h, low=l, close=p, volume=1000 + i))
    return candles


@pytest.fixture
def uptrend_candles():
    return make_candles(300, drift=0.003, vol=0.008, seed=1)


@pytest.fixture
def random_candles():
    return make_candles(300, drift=0.0, vol=0.02, seed=7)
