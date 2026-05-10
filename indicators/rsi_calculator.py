"""
indicators/rsi_calculator.py
============================
RSI doble: RSI(6) para momentum rápido, RSI(14) confirmación.
"""

import pandas as pd
import config


def _rsi(series: pd.Series, period: int) -> pd.Series:
    """Implementación estándar Wilder."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def add_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """Añade rsi_6 y rsi_14."""
    df = df.copy()
    df["rsi_6"] = _rsi(df["close"], config.RSI_FAST)
    df["rsi_14"] = _rsi(df["close"], config.RSI_SLOW)
    return df
