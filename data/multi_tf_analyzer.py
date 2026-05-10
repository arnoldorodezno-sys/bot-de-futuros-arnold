"""
data/multi_tf_analyzer.py
=========================
Analizador multi-timeframe:
  - Descarga 15m, 1H y 4H simultáneamente
  - Aplica todos los indicadores
  - Retorna DataFrames listos para usar en filter_engine
"""

from __future__ import annotations
import logging
from typing import Dict, Optional
import pandas as pd

import config
from indicators.ema_calculator import add_emas
from indicators.supertrend import add_supertrend
from indicators.bollinger import add_bollinger_bands
from indicators.rsi_calculator import add_rsi
from indicators.volume_analyzer import add_volume_analysis

logger = logging.getLogger(__name__)


class MultiTFAnalyzer:
    """Coordina la descarga y enriquecimiento multi-TF."""

    def __init__(self, fetcher) -> None:
        self.fetcher = fetcher

    def get_enriched_dataframes(
        self, symbol: str, limit: int = 500
    ) -> Optional[Dict[str, pd.DataFrame]]:
        """
        Descarga 15m, 1h, 4h y aplica todos los indicadores.
        Retorna dict con keys '15m', '1h', '4h'.
        """
        out: Dict[str, pd.DataFrame] = {}

        for tf in config.TIMEFRAMES:
            df = self.fetcher.fetch(symbol, tf, limit=limit)
            if df is None or df.empty or len(df) < 100:
                logger.warning(f"{symbol} {tf}: datos insuficientes")
                return None
            df = self._enrich(df)
            out[tf] = df

        return out

    @staticmethod
    def _enrich(df: pd.DataFrame) -> pd.DataFrame:
        """Aplica los indicadores en orden."""
        df = add_emas(df)
        df = add_supertrend(df)
        df = add_bollinger_bands(df)
        df = add_rsi(df)
        df = add_volume_analysis(df)
        return df
