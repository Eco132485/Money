from trading_agent.db import Database
from trading_agent.exchange.paper import PaperBroker
from trading_agent.exchange.forex import YahooForexMarketData
from trading_agent.llm import LLMClient


def test_paper_account_restores_after_restart(tmp_path):
    db = Database(str(tmp_path / "paper.db"))
    first = PaperBroker(initial_balance=1000.0, fee_rate=0.0, state_store=db)
    assert first.cash == 1000.0
    assert first.market_buy("FX:EURUSD", 100.0, 1.10).ok
    expected_cash = first.cash
    expected_qty = first.position_qty("FX:EURUSD")

    restarted = PaperBroker(initial_balance=1000.0, fee_rate=0.0, state_store=db)
    assert restarted.cash == expected_cash
    assert restarted.position_qty("FX:EURUSD") == expected_qty


def test_ai_unavailable_fails_closed(monkeypatch):
    client = LLMClient()
    monkeypatch.setattr(client.cfg, "enabled", False)
    result = client.reason_signal({"price": 1.0}, {"action": "buy", "confidence": 0.9})
    assert result["action"] == "hold"
    assert result["confidence"] == 0.0


def test_forex_symbol_mapping():
    assert YahooForexMarketData._ticker("EURUSD") == "EURUSD=X"
    assert YahooForexMarketData._ticker("FX:GBPUSD") == "GBPUSD=X"


def test_invalid_forex_symbol_rejected():
    try:
        YahooForexMarketData._ticker("BTCUSDT")
    except ValueError:
        return
    assert False, "crypto symbols must not be accepted as FX pairs"


def test_shared_exposure_cap_limits_new_trade_size():
    from trading_agent.config import RiskConfig
    from trading_agent.risk_management import RiskManager
    cfg = RiskConfig(max_position_pct=0.30, max_portfolio_exposure_pct=0.30,
                     risk_per_trade_pct=0.01, min_confidence=0.5)
    risk = RiskManager(cfg)
    decision = risk.pre_trade_check(
        equity=1000, price=100, confidence=0.9, current_exposure=290,
        open_positions=1, day_start_equity=1000, peak_equity=1000,
        stop_loss=98, take_profit=104,
    )
    assert decision.approved
    assert 290 + decision.qty * 100 <= 300 + 1e-8


def test_runtime_is_paper_only_even_if_live_env_is_set(monkeypatch):
    from trading_agent.config import RuntimeConfig
    monkeypatch.setenv("TRADING_MODE", "live")
    assert RuntimeConfig().mode == "paper"


def test_forex_short_persists_and_closes_with_profit(tmp_path):
    db = Database(str(tmp_path / "short.db"))
    first = PaperBroker(initial_balance=1000.0, fee_rate=0.0, state_store=db)
    opened = first.market_short("FX:EURUSD", 300.0, 1.10)
    assert opened.ok
    assert first.position_side("FX:EURUSD") == "short"
    assert abs(first.equity({"FX:EURUSD": 1.10}) - 1000.0) < 1e-8

    restarted = PaperBroker(initial_balance=1000.0, fee_rate=0.0, state_store=db)
    assert restarted.position_side("FX:EURUSD") == "short"
    covered = restarted.market_cover("FX:EURUSD", restarted.position_qty("FX:EURUSD"), 1.00)
    assert covered.ok
    assert restarted.position_side("FX:EURUSD") is None
    assert restarted.cash > 1000.0


def test_short_risk_defaults_have_correct_direction():
    from trading_agent.config import RiskConfig
    from trading_agent.risk_management import RiskManager
    rm = RiskManager(RiskConfig(max_position_pct=0.30, max_portfolio_exposure_pct=0.30,
                                risk_per_trade_pct=0.01, min_confidence=0.5))
    decision = rm.pre_trade_check(
        equity=1000, price=1.10, confidence=0.9, current_exposure=0,
        open_positions=0, day_start_equity=1000, peak_equity=1000, side="sell"
    )
    assert decision.approved
    assert decision.stop_loss > 1.10 > decision.take_profit


def test_short_cover_trade_history_records_positive_profit(tmp_path):
    from trading_agent.risk_management import RiskDecision, RiskManager
    from trading_agent.trade_execution import TradeExecutor
    db = Database(str(tmp_path / "short-history.db"))
    broker = PaperBroker(initial_balance=1000.0, fee_rate=0.0, state_store=db)
    executor = TradeExecutor(broker, RiskManager(), db)
    decision = RiskDecision(True, "approved", qty=100.0, stop_loss=1.2,
                            take_profit=1.0, risk_amount=10.0)
    opened = executor.open_short("FX:EURUSD", decision, 1.10, "test", 0.9)
    assert opened and opened.ok
    covered = executor.cover_short("FX:EURUSD", opened.qty, 1.00)
    assert covered and covered.ok
    closed = db.closed_trades()
    assert len(closed) == 1
    assert closed[0]["side"] == "sell"
    assert closed[0]["pnl"] > 0
    assert closed[0]["pnl_pct"] > 0


def test_rejected_buy_does_not_change_short_account_cash():
    broker = PaperBroker(initial_balance=1000.0, fee_rate=0.0)
    assert broker.market_short("FX:EURUSD", 300.0, 1.10).ok
    before = broker.cash
    rejected = broker.market_buy("FX:EURUSD", 100.0, 1.10)
    assert not rejected.ok
    assert broker.cash == before


def test_restart_recovery_rebuilds_missing_trade_record(tmp_path):
    from trading_agent.main import reconcile_paper_state
    from trading_agent.risk_management import RiskManager
    db = Database(str(tmp_path / "recover.db"))
    broker = PaperBroker(initial_balance=1000.0, fee_rate=0.0, state_store=db)
    assert broker.market_buy("BTCUSDT", 200.0, 100.0).ok
    risk = RiskManager()
    reconcile_paper_state(db, broker, risk)
    rows = db.open_trades()
    assert len(rows) == 1
    assert rows[0]["strategy"] == "restart_recovery"
    assert rows[0]["stop_loss"] < rows[0]["entry_price"] < rows[0]["take_profit"]
    assert not risk.killed


def test_orphan_trade_record_triggers_kill_switch(tmp_path):
    from trading_agent.main import reconcile_paper_state
    from trading_agent.risk_management import RiskManager
    db = Database(str(tmp_path / "orphan.db"))
    broker = PaperBroker(initial_balance=1000.0, state_store=db)
    db.open_trade("BTCUSDT", "buy", 1.0, 100.0, "test", 98.0, 104.0)
    risk = RiskManager()
    reconcile_paper_state(db, broker, risk)
    assert risk.killed
    assert "broker position missing" in risk.kill_reason
