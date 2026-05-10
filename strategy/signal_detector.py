"""
strategy/signal_detector.py
===========================
Detección complementaria de señales SMC:
  - Patrones de vela (engulfing, pin bar)
  - Confirmación post-sweep
  - Validación de la dirección general
"""

import pandas as pd
from typing import Literal, Optional, Dict

Direction = Literal["LONG", "SHORT"]


def detect_engulfing(df: pd.DataFrame, direction: Direction) -> bool:
    """
    Vela envolvente bullish/bearish en las últimas 2 velas.
    """
    if len(df) < 2:
        return False
    prev, curr = df.iloc[-2], df.iloc[-1]
    if direction == "LONG":
        return (
            prev["close"] < prev["open"]
            and curr["close"] > curr["open"]
            and curr["close"] > prev["open"]
            and curr["open"] < prev["close"]
        )
    return (
        prev["close"] > prev["open"]
        and curr["close"] < curr["open"]
        and curr["close"] < prev["open"]
        and curr["open"] > prev["close"]
    )


def detect_pin_bar(df: pd.DataFrame, direction: Direction) -> bool:
    """
    Pin bar = mecha dominante (>2x cuerpo) en dirección contraria al cierre.
    """
    if len(df) < 1:
        return False
    last = df.iloc[-1]
    body = abs(last["close"] - last["open"])
    if body == 0:
        return False
    upper_wick = last["high"] - max(last["close"], last["open"])
    lower_wick = min(last["close"], last["open"]) - last["low"]

    if direction == "LONG":
        return lower_wick > body * 2 and lower_wick > upper_wick * 1.5
    return upper_wick > body * 2 and upper_wick > lower_wick * 1.5


def initial_signal_direction(df_1h: pd.DataFrame) -> Optional[Direction]:
    """
    Dirección preliminar basada en EMAs 1H.
    Retorna None si no hay tendencia clara.
    """
    if df_1h.empty or "ema_99" not in df_1h.columns:
        return None
    last = df_1h.iloc[-1]
    if last["ema_7"] > last["ema_25"] > last["ema_99"]:
        return "LONG"
    if last["ema_7"] < last["ema_25"] < last["ema_99"]:
        return "SHORT"
    return None
