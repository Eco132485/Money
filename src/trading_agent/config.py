"""
Central configuration for the autonomous trading agent.

All secrets are loaded from environment variables (or a .env file) — never
hard-coded. Risk parameters and runtime settings are grouped into typed
dataclasses so the rest of the system has a single, validated source of truth.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

try:  # optional dependency; .env is convenient but not required
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _get_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class ExchangeConfig:
    name: str = os.getenv("EXCHANGE", "binance")
    market_type: str = os.getenv("MARKET_TYPE", "spot")  # spot | futures
    base_url: str = os.getenv("EXCHANGE_BASE_URL", "https://api.binance.com")
    api_key: str = os.getenv("EXCHANGE_API_KEY", "")
    api_secret: str = os.getenv("EXCHANGE_API_SECRET", "")
    testnet: bool = _get_bool("EXCHANGE_TESTNET", True)
    quote_asset: str = os.getenv("QUOTE_ASSET", "USDT")


@dataclass
class RiskConfig:
    """Hard risk limits. These are enforced before every order."""
    max_position_pct: float = _get_float("MAX_POSITION_PCT", 0.02)      # 2% equity per trade
    max_portfolio_exposure_pct: float = _get_float("MAX_PORTFOLIO_EXPOSURE_PCT", 0.30)
    max_daily_loss_pct: float = _get_float("MAX_DAILY_LOSS_PCT", 0.03)   # 3% daily loss limit
    max_drawdown_pct: float = _get_float("MAX_DRAWDOWN_PCT", 0.15)       # 15% peak-to-trough
    stop_loss_pct: float = _get_float("STOP_LOSS_PCT", 0.015)            # 1.5%
    take_profit_pct: float = _get_float("TAKE_PROFIT_PCT", 0.03)         # 3%
    min_confidence: float = _get_float("MIN_CONFIDENCE", 0.55)           # only trade above this
    max_open_positions: int = _get_int("MAX_OPEN_POSITIONS", 5)
    risk_per_trade_pct: float = _get_float("RISK_PER_TRADE_PCT", 0.01)   # 1% equity at risk
    kill_switch_enabled: bool = _get_bool("KILL_SWITCH_ENABLED", True)


@dataclass
class LLMConfig:
    """Provider-agnostic LLM settings (OpenAI / Anthropic / rule-based)."""
    provider: str = os.getenv("LLM_PROVIDER", "rule")  # openai | anthropic | rule
    model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    api_key: str = os.getenv("LLM_API_KEY", "")
    base_url: str = os.getenv("LLM_BASE_URL", "")
    temperature: float = _get_float("LLM_TEMPERATURE", 0.2)
    max_tokens: int = _get_int("LLM_MAX_TOKENS", 800)
    enabled: bool = _get_bool("LLM_ENABLED", False)


@dataclass
class NotificationConfig:
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    discord_webhook: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    enabled: bool = _get_bool("NOTIFICATIONS_ENABLED", False)


@dataclass
class RuntimeConfig:
    mode: str = os.getenv("TRADING_MODE", "paper")  # paper | live
    symbols: List[str] = field(default_factory=lambda: [
        s.strip() for s in os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()
    ])
    timeframe: str = os.getenv("TIMEFRAME", "1h")
    loop_interval_sec: int = _get_int("LOOP_INTERVAL_SEC", 60)
    initial_balance: float = _get_float("INITIAL_BALANCE", 10000.0)
    db_path: str = os.getenv("DB_PATH", str(DATA_DIR / "trading.db"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    dashboard_host: str = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    dashboard_port: int = _get_int("DASHBOARD_PORT", 8000)


@dataclass
class Settings:
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

    def to_dict(self) -> dict:
        return asdict(self)


settings = Settings()
