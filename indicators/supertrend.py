"""
indicators/supertrend.py
========================
Implementación de Supertrend (period=10, multiplier=3).
Direction = 1 (verde, alcista) o -1 (rojo, bajista).
"""

import pandas as pd
import numpy as np
import config


def add_supertrend(df: pd.DataFrame) -> pd.DataFrame:
    """
    Añade columnas 'supertrend' y 'supertrend_dir' al DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Debe contener 'high', 'low', 'close'.

    Returns
    -------
    pd.DataFrame con columnas:
      - supertrend: nivel del indicador
      - supertrend_dir: 1 (alcista) o -1 (bajista)
    """
    df = df.copy()
    period = config.SUPERTREND_PERIOD
    multiplier = config.SUPERTREND_MULTIPLIER

    # ATR
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    hl2 = (df["high"] + df["low"]) / 2
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    upper_band = upper_basic.copy()
    lower_band = lower_basic.copy()

    for i in range(1, len(df)):
        if pd.isna(upper_basic.iloc[i]) or pd.isna(upper_band.iloc[i - 1]):
            continue
        if upper_basic.iloc[i] < upper_band.iloc[i - 1] or df["close"].iloc[i - 1] > upper_band.iloc[i - 1]:
            upper_band.iloc[i] = upper_basic.iloc[i]
        else:
            upper_band.iloc[i] = upper_band.iloc[i - 1]

        if lower_basic.iloc[i] > lower_band.iloc[i - 1] or df["close"].iloc[i - 1] < lower_band.iloc[i - 1]:
            lower_band.iloc[i] = lower_basic.iloc[i]
        else:
            lower_band.iloc[i] = lower_band.iloc[i - 1]

    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)

    for i in range(len(df)):
        if i == 0 or pd.isna(atr.iloc[i]):
            supertrend.iloc[i] = np.nan
            direction.iloc[i] = 1
            continue

        prev_st = supertrend.iloc[i - 1]
        if pd.isna(prev_st):
            supertrend.iloc[i] = upper_band.iloc[i]
            direction.iloc[i] = -1
            continue

        if prev_st == upper_band.iloc[i - 1]:
            if df["close"].iloc[i] > upper_band.iloc[i]:
                supertrend.iloc[i] = lower_band.iloc[i]
                direction.iloc[i] = 1
            else:
                supertrend.iloc[i] = upper_band.iloc[i]
                direction.iloc[i] = -1
        else:
            if df["close"].iloc[i] < lower_band.iloc[i]:
                supertrend.iloc[i] = upper_band.iloc[i]
                direction.iloc[i] = -1
            else:
                supertrend.iloc[i] = lower_band.iloc[i]
                direction.iloc[i] = 1

    df["supertrend"] = supertrend
    df["supertrend_dir"] = direction
    return df
