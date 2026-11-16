"""Central, validated configuration. All execution is permanently paper-only."""
from __future__ import annotations
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

def _get_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    return default if val is None else val.strip().lower() in {"1", "true", "yes", "on"}

def _get_float(name: str, default: float) -> float:
    try: return float(os.getenv(name, default))
    except (TypeError, ValueError): return default

def _get_int(name: str, default: int) -> int:
    try: return int(os.getenv(name, default))
    except (TypeError, ValueError): return default

@dataclass
class ExchangeConfig:
    name: str = os.getenv("EXCHANGE", "binance")
    market_type: str = "spot"
    base_url: str = os.getenv("EXCHANGE_BASE_URL", "https://api.binance.com")
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True
    quote_asset: str = "USDT"

@dataclass
class RiskConfig:
    max_position_pct: float = _get_float("MAX_POSITION_PCT", 0.30)
    max_portfolio_exposure_pct: float = _get_float("MAX_PORTFOLIO_EXPOSURE_PCT", 0.30)
    max_daily_loss_pct: float = _get_float("MAX_DAILY_LOSS_PCT", 0.03)
    max_drawdown_pct: float = _get_float("MAX_DRAWDOWN_PCT", 0.15)
    stop_loss_pct: float = _get_float("STOP_LOSS_PCT", 0.015)
    take_profit_pct: float = _get_float("TAKE_PROFIT_PCT", 0.03)
    min_confidence: float = _get_float("MIN_CONFIDENCE", 0.55)
    max_open_positions: int = _get_int("MAX_OPEN_POSITIONS", 5)
    risk_per_trade_pct: float = _get_float("RISK_PER_TRADE_PCT", 0.01)
    kill_switch_enabled: bool = True

@dataclass
class LLMConfig:
    provider: str = "google"
    model: str = "gemini-3.8-flash"
    api_key: str = os.getenv("ISA_GEMINI_API_KEY", "")
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    temperature: float = 0.2
    max_tokens: int = _get_int("LLM_MAX_TOKENS", 800)
    free_tier_confirmed: bool = _get_bool("ISA_GEMINI_FREE_TIER_CONFIRMED", False)
    enabled: bool = bool(os.getenv("ISA_GEMINI_API_KEY")) and _get_bool("ISA_GEMINI_FREE_TIER_CONFIRMED", False)

@dataclass
class NotificationConfig:
    telegram_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook: str = ""
    enabled: bool = False

@dataclass
class RuntimeConfig:
    mode: str = "paper"
    symbols: List[str] = field(default_factory=lambda: [
        s.strip().upper() for s in os.getenv("CRYPTO_SYMBOLS", os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT")).split(",") if s.strip()
    ])
    forex_symbols: List[str] = field(default_factory=lambda: [
        s.strip().upper() for s in os.getenv("FOREX_SYMBOLS", "EURUSD,GBPUSD,USDJPY").split(",") if s.strip()
    ])
    timeframe: str = os.getenv("TIMEFRAME", "1h")
    loop_interval_sec: int = _get_int("LOOP_INTERVAL_SEC", 60)
    initial_balance: float = 1000.0
    db_path: str = os.getenv("DB_PATH", str(DATA_DIR / "trading.db"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    dashboard_host: str = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    dashboard_port: int = _get_int("DASHBOARD_PORT", 8000)

@dataclass
class Settings:
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    def to_dict(self) -> dict: return asdict(self)

settings = Settings()
