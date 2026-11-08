"""
Real-time dashboard: FastAPI backend + lightweight HTML/JS frontend.
Exposes JSON endpoints for equity, trades, positions, signals, logs and
performance, plus a live-updating single-page view.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

# allow running as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_agent.config import settings  # noqa: E402
from trading_agent.db import get_db  # noqa: E402
from trading_agent.monitoring import Monitor  # noqa: E402

app = FastAPI(title="Autonomous Trading Agent")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
db = get_db()
monitor = Monitor(db)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/api/summary")
def summary():
    equity = db.equity_series(limit=1)
    perf = monitor.performance()
    return {
        "mode": settings.runtime.mode,
        "symbols": settings.runtime.symbols,
        "equity": equity[-1]["equity"] if equity else settings.runtime.initial_balance,
        "cash": equity[-1]["cash"] if equity else settings.runtime.initial_balance,
        "exposure": equity[-1]["exposure"] if equity else 0,
        "performance": perf,
        "open_positions": len(db.open_trades()),
    }


@app.get("/api/equity")
def equity():
    return db.equity_series(limit=1000)


@app.get("/api/trades")
def trades():
    return {"open": db.open_trades(), "closed": db.closed_trades(limit=100)}


@app.get("/api/signals")
def signals():
    return db.recent_signals(limit=30)


@app.get("/api/logs")
def logs():
    return db.recent_logs(limit=50)


@app.get("/api/strategies")
def strategies():
    return db.active_strategies()


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.runtime.dashboard_host, port=settings.runtime.dashboard_port)
