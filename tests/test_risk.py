from trading_agent.config import RiskConfig
from trading_agent.risk_management import RiskManager


def make_risk(**kw):
    cfg = RiskConfig(max_position_pct=0.02, min_confidence=0.55,
                     max_daily_loss_pct=0.03, max_drawdown_pct=0.15,
                     max_open_positions=5, max_portfolio_exposure_pct=0.30,
                     risk_per_trade_pct=0.01, stop_loss_pct=0.015,
                     take_profit_pct=0.03)
    for k, v in kw.items():
        setattr(cfg, k, v)
    return RiskManager(cfg)


def test_position_size_capped():
    rm = make_risk()
    qty = rm.position_size(equity=10000, price=100, stop_loss=98.5)
    notional = qty * 100
    assert notional <= 10000 * 0.02 + 1e-6


def test_low_confidence_rejected():
    rm = make_risk()
    d = rm.pre_trade_check(equity=10000, price=100, confidence=0.2,
                           current_exposure=0, open_positions=0,
                           day_start_equity=10000, peak_equity=10000)
    assert not d.approved
    assert "confidence" in d.reason


def test_approved_trade_has_stops():
    rm = make_risk()
    d = rm.pre_trade_check(equity=10000, price=100, confidence=0.8,
                           current_exposure=0, open_positions=0,
                           day_start_equity=10000, peak_equity=10000)
    assert d.approved
    assert d.stop_loss < 100 < d.take_profit
    assert d.qty > 0


def test_daily_loss_triggers_kill_switch():
    rm = make_risk()
    d = rm.pre_trade_check(equity=9600, price=100, confidence=0.9,
                           current_exposure=0, open_positions=0,
                           day_start_equity=10000, peak_equity=10000)
    assert not d.approved
    assert rm.killed


def test_max_drawdown_triggers_kill_switch():
    rm = make_risk()
    d = rm.pre_trade_check(equity=8000, price=100, confidence=0.9,
                           current_exposure=0, open_positions=0,
                           day_start_equity=8000, peak_equity=10000)
    assert not d.approved
    assert rm.killed


def test_exposure_cap():
    rm = make_risk()
    d = rm.pre_trade_check(equity=10000, price=100, confidence=0.9,
                           current_exposure=3500, open_positions=1,
                           day_start_equity=10000, peak_equity=10000)
    assert not d.approved
    assert "exposure" in d.reason


def test_exit_logic():
    rm = make_risk()
    assert rm.check_exit("buy", 100, 98.0, 98.5, 103) == "stop_loss"
    assert rm.check_exit("buy", 100, 104, 98.5, 103) == "take_profit"
    assert rm.check_exit("buy", 100, 101, 98.5, 103) is None
