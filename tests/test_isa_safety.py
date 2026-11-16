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
