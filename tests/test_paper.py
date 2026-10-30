from trading_agent.exchange.paper import PaperBroker


def test_buy_and_equity():
    b = PaperBroker(initial_balance=10000, fee_rate=0.001)
    res = b.market_buy("BTCUSDT", 1000, 100.0)
    assert res.ok
    assert b.position_qty("BTCUSDT") > 0
    # cash reduced by notional + fee
    assert b.cash < 10000 - 1000
    eq = b.equity({"BTCUSDT": 100.0})
    assert abs(eq - (b.cash + b.position_qty("BTCUSDT") * 100.0)) < 1e-6


def test_sell_closes_position():
    b = PaperBroker(initial_balance=10000)
    b.market_buy("ETHUSDT", 500, 50.0)
    qty = b.position_qty("ETHUSDT")
    res = b.market_sell("ETHUSDT", qty, 55.0)
    assert res.ok
    assert b.position_qty("ETHUSDT") == 0
    assert b.cash > 10000  # profit


def test_insufficient_cash_rejected():
    b = PaperBroker(initial_balance=100)
    res = b.market_buy("BTCUSDT", 1000, 100.0)
    assert not res.ok


def test_sell_without_position_rejected():
    b = PaperBroker(initial_balance=10000)
    res = b.market_sell("BTCUSDT", 1, 100.0)
    assert not res.ok


def test_avg_price_on_scale_in():
    b = PaperBroker(initial_balance=10000, fee_rate=0)
    b.market_buy("X", 1000, 100.0)   # 10 units @100
    b.market_buy("X", 1100, 110.0)   # 10 units @110
    pos = b.positions["X"]
    assert abs(pos["avg_price"] - 105.0) < 1e-6
    assert abs(pos["qty"] - 20.0) < 1e-6
