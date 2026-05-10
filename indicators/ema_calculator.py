"""
indicators/ema_calculator.py
============================
Cálculo de Exponential Moving Averages (EMA 7, 25, 99).
"""

import pandas as pd
import config


def add_emas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Añade columnas ema_7, ema_25, ema_99 al DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Debe contener columna 'close'.

    Returns
    -------
    pd.DataFrame
        Mismo DataFrame con columnas EMA añadidas.
    """
    df = df.copy()
    df["ema_7"] = df["close"].ewm(span=config.EMA_FAST, adjust=False).mean()
    df["ema_25"] = df["close"].ewm(span=config.EMA_MID, adjust=False).mean()
    df["ema_99"] = df["close"].ewm(span=config.EMA_SLOW, adjust=False).mean()
    return df


def is_bull_cascade(df: pd.DataFrame) -> bool:
    """EMAs en cascada alcista (ema_7 > ema_25 > ema_99)."""
    if df.empty or "ema_7" not in df.columns:
        return False
    last = df.iloc[-1]
    return last["ema_7"] > last["ema_25"] > last["ema_99"]


def is_bear_cascade(df: pd.DataFrame) -> bool:
    """EMAs en cascada bajista (ema_7 < ema_25 < ema_99)."""
    if df.empty or "ema_7" not in df.columns:
        return False
    last = df.iloc[-1]
    return last["ema_7"] < last["ema_25"] < last["ema_99"]
