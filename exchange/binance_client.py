"""
exchange/binance_client.py
==========================
Wrapper alrededor de python-binance para Binance Futures.
Soporta:
  - Testnet
  - Reconexión automática
  - Retry con backoff exponencial
"""

from __future__ import annotations
import logging
import time
from typing import Any, Dict, List, Optional
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_BASE = 2.0


def with_retry(func):
    """Decorator: reintenta llamadas con backoff exponencial."""
    def wrapper(*args, **kwargs):
        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except (BinanceAPIException, BinanceRequestException, ConnectionError) as e:
                last_exc = e
                wait = RETRY_DELAY_BASE * (2 ** attempt)
                logger.warning(f"{func.__name__} fallo (intento {attempt+1}): {e} - reintento en {wait}s")
                time.sleep(wait)
        logger.error(f"{func.__name__} fallido tras {MAX_RETRIES} intentos: {last_exc}")
        raise last_exc
    return wrapper


class BinanceClient:
    """Cliente Binance Futures con reconexión automática."""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self._client: Optional[Client] = None
        self._connect()

    def _connect(self) -> None:
        """Crea cliente Binance."""
        try:
            self._client = Client(
                api_key=self.api_key,
                api_secret=self.api_secret,
                testnet=self.testnet,
            )
            if self.testnet:
                self._client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
            logger.info(f"Conectado a Binance ({'TESTNET' if self.testnet else 'PROD'})")
        except Exception as e:
            logger.error(f"Error conectando a Binance: {e}")
            raise

    @property
    def client(self) -> Client:
        if self._client is None:
            self._connect()
        return self._client  # type: ignore

    # ------------------------------------------------------------------
    # MARKET DATA
    # ------------------------------------------------------------------
    @with_retry
    def get_klines(self, symbol: str, interval: str, limit: int = 500) -> List[List]:
        """Obtener velas históricas."""
        return self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)

    @with_retry
    def get_ticker_price(self, symbol: str) -> float:
        ticker = self.client.futures_symbol_ticker(symbol=symbol)
        return float(ticker["price"])

    @with_retry
    def get_exchange_info(self) -> Dict[str, Any]:
        return self.client.futures_exchange_info()

    # ------------------------------------------------------------------
    # ACCOUNT / BALANCE
    # ------------------------------------------------------------------
    @with_retry
    def get_futures_balance(self) -> Dict[str, Any]:
        """Retorna balance USDT en futures."""
        balances = self.client.futures_account_balance()
        for b in balances:
            if b["asset"] == "USDT":
                return {
                    "availableBalance": b["availableBalance"],
                    "totalWalletBalance": b["balance"],
                }
        return {"availableBalance": "0", "totalWalletBalance": "0"}

    @with_retry
    def get_open_positions(self) -> List[Dict[str, Any]]:
        return self.client.futures_position_information()

    # ------------------------------------------------------------------
    # ÓRDENES
    # ------------------------------------------------------------------
    @with_retry
    def set_leverage(self, symbol: str, leverage: int) -> Dict:
        return self.client.futures_change_leverage(symbol=symbol, leverage=leverage)

    @with_retry
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Orden de mercado. side: BUY o SELL."""
        return self.client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity,
        )

    @with_retry
    def place_stop_loss(self, symbol: str, side: str, stop_price: float, quantity: float) -> Dict:
        """SL como STOP_MARKET reduceOnly."""
        return self.client.futures_create_order(
            symbol=symbol,
            side=side,
            type="STOP_MARKET",
            stopPrice=stop_price,
            closePosition=False,
            quantity=quantity,
            reduceOnly=True,
            timeInForce="GTC",
        )

    @with_retry
    def place_take_profit(self, symbol: str, side: str, stop_price: float, quantity: float) -> Dict:
        """TP como TAKE_PROFIT_MARKET reduceOnly."""
        return self.client.futures_create_order(
            symbol=symbol,
            side=side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=stop_price,
            quantity=quantity,
            reduceOnly=True,
            timeInForce="GTC",
        )

    @with_retry
    def cancel_all_orders(self, symbol: str) -> Dict:
        return self.client.futures_cancel_all_open_orders(symbol=symbol)

    @with_retry
    def update_stop_loss(self, symbol: str, direction: str, new_sl: float) -> None:
        """Cancela SL anterior y crea uno nuevo."""
        # Buscar órdenes SL abiertas
        open_orders = self.client.futures_get_open_orders(symbol=symbol)
        for order in open_orders:
            if order["type"] == "STOP_MARKET" and order["reduceOnly"]:
                self.client.futures_cancel_order(symbol=symbol, orderId=order["orderId"])
        # Recrear con nuevo precio
        # Necesitamos cantidad y side desde la posición actual
        positions = self.get_open_positions()
        for pos in positions:
            if pos["symbol"] == symbol and abs(float(pos["positionAmt"])) > 0:
                qty = abs(float(pos["positionAmt"]))
                side = "SELL" if direction == "LONG" else "BUY"
                self.place_stop_loss(symbol, side, new_sl, qty)
                break
