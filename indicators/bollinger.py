"""
indicators/bollinger.py
=======================
Bollinger Bands con periodo 20 y 2 desviaciones estándar.
"""

import pandas as pd
import config


def add_bollinger_bands(df: pd.DataFrame) -> pd.DataFrame:
    """
    Añade bb_lower, bb_mid, bb_upper.
    """
    df = df.copy()
    period = config.BB_PERIOD
    std = config.BB_STD
    df["bb_mid"] = df["close"].rolling(period).mean()
    rolling_std = df["close"].rolling(period).std()
    df["bb_upper"] = df["bb_mid"] + std * rolling_std
    df["bb_lower"] = df["bb_mid"] - std * rolling_std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    return df


def is_near_upper(df: pd.DataFrame, threshold: float = None) -> bool:
    """¿Precio actual cerca de banda superior?"""
    if threshold is None:
        threshold = config.BB_UPPER_PROXIMITY
    last = df.iloc[-1]
    return last["close"] >= last["bb_upper"] * (1 - threshold)


def is_near_lower(df: pd.DataFrame, threshold: float = None) -> bool:
    """¿Precio actual cerca de banda inferior?"""
    if threshold is None:
        threshold = config.BB_LOWER_PROXIMITY
    last = df.iloc[-1]
    return last["close"] <= last["bb_lower"] * (1 + threshold)
