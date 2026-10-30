from trading_agent.market_analysis import candles_to_df
from trading_agent.strategy_engine import (
    StrategyEngine, TrendFollow, MeanReversion, Breakout, backtest_candles,
)


def test_engine_generates_signal(uptrend_candles):
    df = candles_to_df(uptrend_candles)
    sig = StrategyEngine().generate(df)
    assert sig.action in {"buy", "sell", "hold"}
    assert 0.0 <= sig.confidence <= 1.0


def test_backtest_metrics_shape(uptrend_candles):
    df = candles_to_df(uptrend_candles)
    for strat in (TrendFollow(), MeanReversion(), Breakout()):
        m = strat.backtest(df)
        assert "error" not in m
        for key in ("total_return", "sharpe", "max_drawdown", "win_rate", "profit_factor"):
            assert key in m


def test_no_conviction_returns_hold():
    from trading_agent.strategy_engine import Signal
    from tests.conftest import make_candles
    df = candles_to_df(make_candles(120, drift=0.0, vol=0.0001, seed=3))
    sig = StrategyEngine().generate(df)
    if sig.confidence == 0.0:
        assert sig.action == "hold"


def test_backtest_all(random_candles):
    res = backtest_candles(random_candles)
    assert set(res.keys()) == {"trend_follow", "mean_reversion", "breakout"}
    for m in res.values():
        assert m["max_drawdown"] <= 0.0
        assert m["num_trades"] >= 0


def test_insufficient_data():
    from tests.conftest import make_candles
    m = TrendFollow().backtest(candles_to_df(make_candles(10)))
    assert "error" in m
