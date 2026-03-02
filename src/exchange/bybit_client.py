from __future__ import annotations

import time

import ccxt
import pandas as pd

from src.core.config import ExchangeConfig
from src.core.enums import MarketType, Side
from src.core.exceptions import ExchangeError
from src.core.models import Fill, Order, Position
from src.exchange.base import ExchangeClient
from src.utils.logger import get_logger

logger = get_logger("exchange.bybit")


class BybitClient(ExchangeClient):
    """Bybit exchange client via ccxt. Supports spot and USDT perpetual futures."""

    def __init__(self):
        self._exchange: ccxt.bybit | None = None

    def connect(self, config: ExchangeConfig) -> None:
        self._exchange = ccxt.bybit({
            "apiKey": config.api_key or None,
            "secret": config.api_secret or None,
            "enableRateLimit": config.rate_limit,
            "options": {
                "defaultType": "swap",
            },
        })
        if config.testnet:
            self._exchange.set_sandbox_mode(True)
            logger.info("Connected to Bybit TESTNET")
        else:
            logger.info("Connected to Bybit MAINNET")

        try:
            self._exchange.load_markets()
            logger.info(f"Loaded {len(self._exchange.markets)} markets")
        except Exception as e:
            raise ExchangeError(f"Failed to load markets: {e}") from e

    @property
    def exchange(self) -> ccxt.bybit:
        if self._exchange is None:
            raise ExchangeError("Exchange not connected. Call connect() first.")
        return self._exchange

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        try:
            raw = self.exchange.fetch_ohlcv(
                symbol, timeframe, since=since, limit=limit
            )
        except ccxt.BaseError as e:
            raise ExchangeError(f"Failed to fetch OHLCV for {symbol}: {e}") from e

        if not raw:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = df["timestamp"].astype(int)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df

    def fetch_ticker(self, symbol: str) -> dict:
        try:
            return self.exchange.fetch_ticker(symbol)
        except ccxt.BaseError as e:
            raise ExchangeError(f"Failed to fetch ticker for {symbol}: {e}") from e

    def fetch_balance(self) -> dict:
        try:
            return self.exchange.fetch_balance()
        except ccxt.BaseError as e:
            raise ExchangeError(f"Failed to fetch balance: {e}") from e

    def create_order(self, order: Order) -> Fill:
        params = {}
        if order.stop_loss:
            params["stopLoss"] = {"triggerPrice": str(order.stop_loss)}
        if order.take_profit:
            params["takeProfit"] = {"triggerPrice": str(order.take_profit)}
        params.update(order.params)

        try:
            result = self.exchange.create_order(
                symbol=order.symbol,
                type=order.order_type.value,
                side=order.side.value,
                amount=order.quantity,
                price=order.price,
                params=params,
            )
        except ccxt.BaseError as e:
            raise ExchangeError(f"Failed to create order: {e}") from e

        fill_price = float(result.get("average") or result.get("price") or 0)
        fill_qty = float(result.get("filled") or order.quantity)
        fee_cost = float(result.get("fee", {}).get("cost", 0))

        logger.info(
            f"Order filled: {order.side.value} {order.symbol} "
            f"qty={fill_qty} price={fill_price}"
        )

        return Fill(
            order_id=result["id"],
            symbol=order.symbol,
            side=order.side,
            quantity=fill_qty,
            price=fill_price,
            fee=fee_cost,
            timestamp=result.get("timestamp", int(time.time() * 1000)),
        )

    def cancel_order(self, order_id: str, symbol: str) -> None:
        try:
            self.exchange.cancel_order(order_id, symbol)
            logger.info(f"Cancelled order {order_id} for {symbol}")
        except ccxt.BaseError as e:
            raise ExchangeError(f"Failed to cancel order {order_id}: {e}") from e

    def fetch_positions(self, symbol: str | None = None) -> list[Position]:
        try:
            if symbol:
                raw = self.exchange.fetch_positions([symbol])
            else:
                raw = self.exchange.fetch_positions()
        except ccxt.BaseError as e:
            raise ExchangeError(f"Failed to fetch positions: {e}") from e

        positions = []
        for p in raw:
            qty = float(p.get("contracts", 0) or 0)
            if qty == 0:
                continue
            side = Side.BUY if p.get("side") == "long" else Side.SELL
            positions.append(Position(
                symbol=p["symbol"],
                side=side,
                quantity=qty,
                entry_price=float(p.get("entryPrice", 0) or 0),
                current_price=float(p.get("markPrice", 0) or 0),
                market_type=MarketType.FUTURES,
                stop_loss=float(p.get("stopLossPrice", 0) or 0) or None,
                take_profit=float(p.get("takeProfitPrice", 0) or 0) or None,
            ))
        return positions

    def set_leverage(self, symbol: str, leverage: int) -> None:
        try:
            self.exchange.set_leverage(leverage, symbol)
            logger.info(f"Set leverage to {leverage}x for {symbol}")
        except ccxt.BaseError as e:
            # Some exchanges throw if leverage is already set
            logger.warning(f"Set leverage warning for {symbol}: {e}")

    def fetch_funding_rate(self, symbol: str) -> dict:
        """Fetch the current funding rate for a perpetual contract.

        Returns:
            dict with keys: symbol, funding_rate, funding_timestamp
        """
        try:
            result = self.exchange.fetch_funding_rate(symbol)
            return {
                "symbol": symbol,
                "funding_rate": float(result.get("fundingRate", 0)),
                "funding_timestamp": result.get("fundingTimestamp", 0),
            }
        except ccxt.BaseError as e:
            raise ExchangeError(
                f"Failed to fetch funding rate for {symbol}: {e}"
            ) from e

    def update_trading_stop(self, symbol: str, stop_loss: float) -> None:
        """Update stop-loss on an existing position (for trailing stop)."""
        try:
            market = self.exchange.market(symbol)
            self.exchange.private_post_v5_position_trading_stop({
                "category": "linear",
                "symbol": market["id"],
                "stopLoss": str(round(stop_loss, 2)),
                "positionIdx": 0,  # one-way mode
            })
            logger.debug(f"Updated trading stop for {symbol}: SL={stop_loss:.2f}")
        except ccxt.BaseError as e:
            raise ExchangeError(f"Failed to update trading stop for {symbol}: {e}") from e
