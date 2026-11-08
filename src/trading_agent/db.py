"""SQLite persistence layer for trades, orders, equity, signals, logs and strategies."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

from .config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL NOT NULL,
    type TEXT NOT NULL DEFAULT 'market',
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    reason TEXT,
    confidence REAL
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    pnl REAL,
    pnl_pct REAL,
    fee REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    strategy TEXT,
    stop_loss REAL,
    take_profit REAL,
    closed_ts REAL
);
CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    equity REAL NOT NULL,
    cash REAL NOT NULL,
    exposure REAL NOT NULL DEFAULT 0,
    mode TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence REAL NOT NULL,
    price REAL NOT NULL,
    meta TEXT
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    level TEXT NOT NULL,
    module TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    name TEXT NOT NULL,
    params TEXT NOT NULL,
    metrics TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(ts);
CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity(ts);
"""


class Database:
    """Thread-safe SQLite wrapper (one connection per thread)."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or settings.runtime.db_path
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            self._local.conn = conn
        return conn

    @contextmanager
    def cursor(self):
        conn = self._conn()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        finally:
            cur.close()

    def _ensure_schema(self) -> None:
        with self._init_lock:
            with self.cursor() as cur:
                cur.executescript(SCHEMA)

    # ---- orders ----
    def record_order(self, symbol: str, side: str, qty: float, price: float,
                     status: str, mode: str, order_type: str = "market",
                     reason: str = "", confidence: float = 0.0) -> int:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO orders (ts,symbol,side,qty,price,type,status,mode,reason,confidence)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (time.time(), symbol, side, qty, price, order_type, status, mode, reason, confidence),
            )
            return cur.lastrowid

    # ---- trades ----
    def open_trade(self, symbol: str, side: str, qty: float, entry_price: float,
                   strategy: str, stop_loss: float, take_profit: float,
                   fee: float = 0.0) -> int:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO trades (ts,symbol,side,qty,entry_price,fee,status,strategy,stop_loss,take_profit)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (time.time(), symbol, side, qty, entry_price, fee, "open", strategy, stop_loss, take_profit),
            )
            return cur.lastrowid

    def close_trade(self, trade_id: int, exit_price: float, pnl: float, pnl_pct: float) -> None:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE trades SET exit_price=?, pnl=?, pnl_pct=?, status='closed', closed_ts=? WHERE id=?",
                (exit_price, pnl, pnl_pct, time.time(), trade_id),
            )

    def open_trades(self) -> List[Dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM trades WHERE status='open' ORDER BY ts")
            return [dict(r) for r in cur.fetchall()]

    def closed_trades(self, limit: int = 500) -> List[Dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM trades WHERE status='closed' ORDER BY ts DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    # ---- equity ----
    def record_equity(self, equity: float, cash: float, exposure: float, mode: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO equity (ts,equity,cash,exposure,mode) VALUES (?,?,?,?,?)",
                (time.time(), equity, cash, exposure, mode),
            )

    def equity_series(self, limit: int = 2000) -> List[Dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM (SELECT * FROM equity ORDER BY ts DESC LIMIT ?) ORDER BY ts", (limit,))
            return [dict(r) for r in cur.fetchall()]

    def peak_equity(self) -> float:
        with self.cursor() as cur:
            cur.execute("SELECT MAX(equity) AS m FROM equity")
            row = cur.fetchone()
            return float(row["m"]) if row and row["m"] is not None else 0.0

    def day_start_equity(self) -> Optional[float]:
        start = time.time() - (time.time() % 86400)
        with self.cursor() as cur:
            cur.execute("SELECT equity FROM equity WHERE ts>=? ORDER BY ts LIMIT 1", (start,))
            row = cur.fetchone()
            return float(row["equity"]) if row else None

    # ---- signals ----
    def record_signal(self, symbol: str, strategy: str, action: str,
                      confidence: float, price: float, meta: Dict[str, Any]) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO signals (ts,symbol,strategy,action,confidence,price,meta) VALUES (?,?,?,?,?,?,?)",
                (time.time(), symbol, strategy, action, confidence, price, json.dumps(meta)),
            )

    def recent_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM signals ORDER BY ts DESC LIMIT ?", (limit,))
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            try:
                r["meta"] = json.loads(r["meta"]) if r["meta"] else {}
            except Exception:
                r["meta"] = {}
        return rows

    # ---- logs ----
    def log(self, level: str, module: str, message: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO logs (ts,level,module,message) VALUES (?,?,?,?)",
                (time.time(), level, module, message),
            )

    def recent_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM logs ORDER BY ts DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    # ---- strategies ----
    def save_strategy(self, name: str, params: Dict[str, Any], metrics: Dict[str, Any],
                      active: bool = True) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO strategies (ts,name,params,metrics,active) VALUES (?,?,?,?,?)",
                (time.time(), name, json.dumps(params), json.dumps(metrics), int(active)),
            )

    def active_strategies(self) -> List[Dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM strategies WHERE active=1 ORDER BY ts DESC")
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["params"] = json.loads(r["params"])
            r["metrics"] = json.loads(r["metrics"])
        return rows


_db_singleton: Optional[Database] = None


def get_db() -> Database:
    global _db_singleton
    if _db_singleton is None:
        _db_singleton = Database()
    return _db_singleton
