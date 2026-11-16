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
