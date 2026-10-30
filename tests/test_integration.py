"""End-to-end trade lifecycle against a temp database (no network)."""
import tempfile
import os

from trading_agent.db import Database
from trading_agent.exchange.paper import PaperBroker
from trading_agent.risk_management import RiskManager
from trading_agent.trade_execution import TradeExecutor
from trading_agent.monitoring import Monitor


def test_full_trade_lifecycle():
    tmp = tempfile.mktemp(suffix=".db")
    try:
        db = Database(tmp)
        broker = PaperBroker(initial_balance=10000, fee_rate=0.001)
        risk = RiskManager()
        ex = TradeExecutor(broker, risk, db)

        price = 100.0
        equity = broker.equity({"BTCUSDT": price})
        decision = risk.pre_trade_check(
            equity=equity, price=price, confidence=0.8,
            current_exposure=0, open_positions=0,
            day_start_equity=equity, peak_equity=equity,
        )
        assert decision.approved

        res = ex.buy("BTCUSDT", decision, price, "test_strategy", 0.8)
        assert res.ok
        assert len(db.open_trades()) == 1

        # price rises -> take profit exit
        exit_price = decision.take_profit + 0.01
        ex.sell("BTCUSDT", broker.position_qty("BTCUSDT"), exit_price, reason="take_profit")
        assert len(db.open_trades()) == 0
        closed = db.closed_trades()
        assert len(closed) == 1
        assert closed[0]["pnl"] > 0

        db.record_equity(broker.equity({"BTCUSDT": exit_price}), broker.cash, 0, "paper")
        perf = Monitor(db).performance()
        assert perf["num_trades"] == 1
        assert perf["win_rate"] == 1.0
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(tmp + suffix)
            except OSError:
                pass
