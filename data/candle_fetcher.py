"""
data/candle_fetcher.py
======================
Descarga velas OHLCV de Binance Futures y las convierte a DataFrame pandas.
"""

from __future__ import annotations
import logging
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)


class CandleFetcher:
    """Descarga y parsea velas de Binance."""

    def __init__(self, client) -> None:
        self.client = client

    def fetch(self, symbol: str, interval: str, limit: int = 500) -> Optional[pd.DataFrame]:
        """
        Descarga `limit` velas de `symbol` en `interval`.
        Retorna DataFrame con columnas: open_time, open, high, low, close, volume, close_time.
        """
        try:
            raw = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
            if not raw:
                logger.warning(f"Sin datos para {symbol} {interval}")
                return None

            df = pd.DataFrame(
                raw,
                columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_volume", "trades",
                    "taker_buy_base", "taker_buy_quote", "ignore",
                ],
            )
            for col in ("open", "high", "low", "close", "volume"):
                df[col] = df[col].astype(float)
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
            return df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]

        except Exception as e:
            logger.exception(f"Error descargando velas {symbol} {interval}: {e}")
            return None
