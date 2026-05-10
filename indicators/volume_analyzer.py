"""
indicators/volume_analyzer.py
=============================
Volumen con MA(5) y MA(10).
Detección de volumen institucional anómalo.
"""

import pandas as pd
import config


def add_volume_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """Añade vol_ma_5, vol_ma_10, vol_ratio."""
    df = df.copy()
    if "volume" not in df.columns:
        return df
    df["vol_ma_5"] = df["volume"].rolling(config.VOL_MA_FAST).mean()
    df["vol_ma_10"] = df["volume"].rolling(config.VOL_MA_SLOW).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma_10"]
    return df


def is_institutional_volume(df: pd.DataFrame, candle_idx: int = -1) -> bool:
    """
    ¿La vela tiene volumen > 1.5x MA(10)?
    """
    if "vol_ma_10" not in df.columns:
        return False
    row = df.iloc[candle_idx]
    if pd.isna(row["vol_ma_10"]) or row["vol_ma_10"] == 0:
        return False
    return row["volume"] > row["vol_ma_10"] * config.VOL_SWEEP_MULTIPLIER


def is_volume_decreasing(df: pd.DataFrame, last_n: int = 3) -> bool:
    """¿Volumen decreciente en las últimas n velas (pullback saludable)?"""
    if len(df) < last_n:
        return False
    recent = df["volume"].iloc[-last_n:].values
    return all(recent[i] >= recent[i + 1] for i in range(len(recent) - 1))
