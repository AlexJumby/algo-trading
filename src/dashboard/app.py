"""Trading bot dashboard — FastAPI backend.

Reads portfolio.db (written by the bot) and serves JSON + static HTML.
Protected by Bearer token authentication.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.portfolio.persistence import PortfolioDB
from src.utils.logger import setup_logging, get_logger

setup_logging(log_level="INFO")
logger = get_logger("dashboard")

DB_PATH = os.getenv("PORTFOLIO_DB_PATH", "data/portfolio.db")

# Auth token: from env or auto-generated
AUTH_TOKEN = os.getenv("DASHBOARD_TOKEN") or secrets.token_urlsafe(32)
if not os.getenv("DASHBOARD_TOKEN"):
    # Print to stdout so operator can see token at startup
    print(f"[Dashboard] Generated auth token: {AUTH_TOKEN}")  # noqa: T201

app = FastAPI(title="Algo Trading Dashboard")

# ── Auth middleware ───────────────────────────────────────────────────
# Exempt paths: static assets, root page, health check
_PUBLIC_PREFIXES = ("/static", "/api/health", "/docs", "/openapi.json")


@app.middleware("http")
async def token_auth_middleware(request: Request, call_next):
    path = request.url.path
    # Allow public paths (static files, index, health)
    if path == "/" or path.startswith(_PUBLIC_PREFIXES):
        return await call_next(request)

    # Check Bearer token
    auth_header = request.headers.get("authorization", "")
    if auth_header == f"Bearer {AUTH_TOKEN}":
        return await call_next(request)

    return JSONResponse(
        status_code=401,
        content={"detail": "Unauthorized — provide Authorization: Bearer <token>"},
    )


# Serve static files (index.html, etc.)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _get_db() -> PortfolioDB:
    """Open DB read-only per request (WAL allows concurrent reads)."""
    return PortfolioDB(DB_PATH)


# ------------------------------------------------------------------
# API endpoints
# ------------------------------------------------------------------

@app.get("/")
async def index():
    """Serve the main dashboard page."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def api_status():
    """Current portfolio status."""
    db = _get_db()
    try:
        snap = db.get_latest_snapshot()
        positions = db.get_open_positions()
        trade_count = db.get_trade_count()
        total_pnl = db.get_total_realized_pnl()
        total_fees = db.get_total_fees()

        return {
            "snapshot": snap,
            "open_positions": positions,
            "trade_count": trade_count,
            "total_realized_pnl": total_pnl,
            "total_fees": total_fees,
        }
    finally:
        db.close()


@app.get("/api/equity")
async def api_equity(since: int = 0, limit: int = 10000):
    """Equity curve data for charting."""
    db = _get_db()
    try:
        curve = db.get_equity_curve(since_ts=since, limit=limit)
        return {"equity_curve": curve}
    finally:
        db.close()


@app.get("/api/trades")
async def api_trades(limit: int = 100):
    """Recent closed trades."""
    db = _get_db()
    try:
        trades = db.get_trades(limit=limit)
        return {"trades": trades}
    finally:
        db.close()


@app.get("/api/health")
async def api_health():
    """Health check for monitoring."""
    return {"status": "ok", "db_path": DB_PATH}
