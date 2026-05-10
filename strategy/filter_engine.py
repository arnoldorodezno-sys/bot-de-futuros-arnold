"""
strategy/filter_engine.py
=========================
Implementación de los 7 filtros obligatorios SMC.
Cada filtro retorna FilterResult con:
  - passed: bool
  - reason: str (razón legible)
  - data: dict (información para scoring/notificaciones)

ORDEN DE EJECUCIÓN (cortocircuito en críticos):
  1. Tendencia macro (CRÍTICO)
  2. Liquidity sweep (CRÍTICO)
  3. Order Block
  4. RSI (CRÍTICO)
  5. Confluencias (mínimo 3/5)
  6. Volumen institucional
  7. Risk/Reward >= 1:2 (CRÍTICO)
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple
import pandas as pd
import numpy as np

import config

logger = logging.getLogger(__name__)

Direction = Literal["LONG", "SHORT"]


@dataclass
class FilterResult:
    """Resultado individual de un filtro."""
    filter_id: int
    name: str
    passed: bool
    critical: bool
    reason: str = ""
    data: Dict = field(default_factory=dict)


@dataclass
class FilterReport:
    """Reporte completo tras pasar todos los filtros."""
    direction: Direction
    symbol: str
    results: List[FilterResult] = field(default_factory=list)
    entry_price: float = 0.0
    stop_loss: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
    confluences: List[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def critical_failed(self) -> List[int]:
        return [r.filter_id for r in self.results if r.critical and not r.passed]

    @property
    def passed_filters(self) -> List[int]:
        return [r.filter_id for r in self.results if r.passed]


# ==========================================================================
# FILTRO 1 - TENDENCIA MACRO
# ==========================================================================
def filter_1_macro_trend(
    direction: Direction,
    df_15m: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_4h: pd.DataFrame,
) -> FilterResult:
    """
    Verifica:
      - Supertrend en mismo color en >=2/3 TF
      - EMAs en cascada en 4H y 1H
      - Precio sobre/bajo EMA99 en 1H
    """
    expected_st = 1 if direction == "LONG" else -1

    st_count = sum(
        1 for df in (df_15m, df_1h, df_4h)
        if not df.empty and df["supertrend_dir"].iloc[-1] == expected_st
    )

    if st_count < 2:
        return FilterResult(
            1, "Tendencia Macro", False, True,
            f"Supertrend {expected_st} solo en {st_count}/3 TF (requiere >=2)",
        )

    def emas_aligned(df: pd.DataFrame, dir_: Direction) -> bool:
        if df.empty:
            return False
        last = df.iloc[-1]
        if dir_ == "LONG":
            return last["ema_7"] > last["ema_25"] > last["ema_99"]
        return last["ema_7"] < last["ema_25"] < last["ema_99"]

    if not emas_aligned(df_4h, direction):
        return FilterResult(1, "Tendencia Macro", False, True, "EMAs 4H no alineadas")
    if not emas_aligned(df_1h, direction):
        return FilterResult(1, "Tendencia Macro", False, True, "EMAs 1H no alineadas")

    last_1h = df_1h.iloc[-1]
    if direction == "LONG" and last_1h["close"] < last_1h["ema_99"]:
        return FilterResult(1, "Tendencia Macro", False, True, "Precio bajo EMA99 1H")
    if direction == "SHORT" and last_1h["close"] > last_1h["ema_99"]:
        return FilterResult(1, "Tendencia Macro", False, True, "Precio sobre EMA99 1H")

    return FilterResult(
        1, "Tendencia Macro", True, True,
        f"Supertrend {st_count}/3 TF alineado, EMAs en cascada",
        {"supertrend_count": st_count},
    )


# ==========================================================================
# FILTRO 2 - LIQUIDITY SWEEP
# ==========================================================================
def filter_2_liquidity_sweep(
    direction: Direction,
    df: pd.DataFrame,
    lookback: int = config.SWEEP_LOOKBACK,
) -> FilterResult:
    """
    Detecta sweep:
      - LONG: mecha barre mínimo previo SIN cerrar fuera (rechazo)
      - SHORT: mecha barre máximo previo SIN cerrar fuera
      - Debe ser en últimas N velas
    """
    if len(df) < lookback + 5:
        return FilterResult(2, "Liquidity Sweep", False, True, "Datos insuficientes")

    recent = df.iloc[-lookback:].copy()
    prior = df.iloc[-(lookback + 20):-lookback]

    if direction == "LONG":
        prior_low = prior["low"].min()
        for idx, row in recent.iterrows():
            if row["low"] < prior_low and row["close"] > prior_low:
                wick_size = row["close"] - row["low"]
                body_size = abs(row["close"] - row["open"])
                if wick_size > body_size * 1.5:  # mecha dominante
                    return FilterResult(
                        2, "Liquidity Sweep", True, True,
                        "Sweep mínimo previo con rechazo",
                        {"sweep_low": float(row["low"]), "candle_idx": int(idx) if isinstance(idx, (int, np.integer)) else -1},
                    )
        return FilterResult(2, "Liquidity Sweep", False, True, "Sin sweep válido en lookback")

    # SHORT
    prior_high = prior["high"].max()
    for idx, row in recent.iterrows():
        if row["high"] > prior_high and row["close"] < prior_high:
            wick_size = row["high"] - row["close"]
            body_size = abs(row["close"] - row["open"])
            if wick_size > body_size * 1.5:
                return FilterResult(
                    2, "Liquidity Sweep", True, True,
                    "Sweep máximo previo con rechazo",
                    {"sweep_high": float(row["high"])},
                )
    return FilterResult(2, "Liquidity Sweep", False, True, "Sin sweep válido en lookback")


# ==========================================================================
# FILTRO 3 - ORDER BLOCK
# ==========================================================================
def find_order_blocks(df: pd.DataFrame, direction: Direction, lookback: int = 50) -> List[Dict]:
    """
    OB bullish: última vela bajista antes de movimiento alcista que rompe estructura.
    OB bearish: última vela alcista antes de movimiento bajista que rompe estructura.
    """
    obs = []
    if len(df) < lookback + 5:
        return obs

    sub = df.iloc[-lookback:].copy().reset_index(drop=True)
    for i in range(2, len(sub) - 3):
        if direction == "LONG":
            # Vela bajista seguida de impulso alcista que rompe el alto siguiente
            if sub.loc[i, "close"] < sub.loc[i, "open"]:
                future_high = sub.loc[i + 1:i + 3, "high"].max()
                if future_high > sub.loc[i, "high"] * 1.002:  # +0.2% impulso
                    obs.append({
                        "type": "bullish",
                        "low": float(sub.loc[i, "low"]),
                        "high": float(sub.loc[i, "high"]),
                        "mid": float((sub.loc[i, "low"] + sub.loc[i, "high"]) / 2),
                        "age": len(sub) - i,
                    })
        else:
            if sub.loc[i, "close"] > sub.loc[i, "open"]:
                future_low = sub.loc[i + 1:i + 3, "low"].min()
                if future_low < sub.loc[i, "low"] * 0.998:
                    obs.append({
                        "type": "bearish",
                        "low": float(sub.loc[i, "low"]),
                        "high": float(sub.loc[i, "high"]),
                        "mid": float((sub.loc[i, "low"] + sub.loc[i, "high"]) / 2),
                        "age": len(sub) - i,
                    })
    return obs


def filter_3_order_block(
    direction: Direction,
    df_15m: pd.DataFrame,
    current_price: float,
) -> FilterResult:
    """
    Busca OB no mitigado, calcula entrada en 50% del OB.
    """
    obs = find_order_blocks(df_15m, direction, lookback=config.OB_MAX_AGE_CANDLES)
    if not obs:
        return FilterResult(3, "Order Block", False, False, "Sin OB válido detectado")

    # Filtrar OB no mitigados (precio aún no los ha tocado de vuelta completamente)
    valid = []
    for ob in obs:
        if direction == "LONG" and current_price > ob["mid"]:
            valid.append(ob)
        elif direction == "SHORT" and current_price < ob["mid"]:
            valid.append(ob)

    if not valid:
        return FilterResult(3, "Order Block", False, False, "Todos los OB están mitigados")

    # Tomar el OB más reciente
    ob = min(valid, key=lambda x: x["age"])
    return FilterResult(
        3, "Order Block", True, False,
        f"OB {ob['type']} válido @ {ob['mid']:.2f}",
        {"ob": ob, "entry": ob["mid"]},
    )


# ==========================================================================
# FILTRO 4 - RSI DOBLE
# ==========================================================================
def filter_4_rsi(
    direction: Direction,
    df_15m: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_4h: pd.DataFrame,
) -> FilterResult:
    """
    LONG válido: RSI(14) 1H ∈ [35, 60]
    SHORT válido: RSI(14) 1H ∈ [40, 65]
    Bloqueos por RSI(6) extremos en cualquier TF.
    """
    rsi_14_1h = df_1h["rsi_14"].iloc[-1]

    if direction == "LONG":
        if not (config.RSI_LONG_MIN <= rsi_14_1h <= config.RSI_LONG_MAX):
            return FilterResult(
                4, "RSI", False, True,
                f"RSI(14) 1H = {rsi_14_1h:.1f} fuera de [35-60]",
            )
        # RSI(6) > 70 en cualquier TF bloquea LONG
        for tf, df in (("15m", df_15m), ("1h", df_1h), ("4h", df_4h)):
            if df["rsi_6"].iloc[-1] > config.RSI_FAST_LONG_BLOCK:
                return FilterResult(
                    4, "RSI", False, True,
                    f"RSI(6) {tf} = {df['rsi_6'].iloc[-1]:.1f} > 70 (sobrecompra)",
                )
    else:  # SHORT
        if not (config.RSI_SHORT_MIN <= rsi_14_1h <= config.RSI_SHORT_MAX):
            return FilterResult(
                4, "RSI", False, True,
                f"RSI(14) 1H = {rsi_14_1h:.1f} fuera de [40-65]",
            )
        for tf, df in (("15m", df_15m), ("1h", df_1h), ("4h", df_4h)):
            if df["rsi_6"].iloc[-1] < config.RSI_FAST_SHORT_BLOCK:
                return FilterResult(
                    4, "RSI", False, True,
                    f"RSI(6) {tf} = {df['rsi_6'].iloc[-1]:.1f} < 30 (sobreventa)",
                )

    return FilterResult(
        4, "RSI", True, True,
        f"RSI(14) 1H = {rsi_14_1h:.1f} en rango válido",
        {"rsi_14_1h": float(rsi_14_1h)},
    )


# ==========================================================================
# FILTRO 5 - CONFLUENCIAS (mínimo 3/5)
# ==========================================================================
def filter_5_confluences(
    direction: Direction,
    df_15m: pd.DataFrame,
    ob_data: Optional[Dict],
    sweep_data: Optional[Dict],
    swing_high: float,
    swing_low: float,
    current_price: float,
) -> FilterResult:
    """
    5 confluencias posibles:
      1. Fibonacci 50% / 61.8% en zona de entrada
      2. FVG dentro/cerca del OB
      3. Bollinger: precio cerca de banda relevante
      4. Supertrend como soporte/resistencia dinámico
      5. Patrón BOS/CHoCH confirmado
    """
    confluences: List[str] = []
    last = df_15m.iloc[-1]

    # 1. Fibonacci
    fib_range = swing_high - swing_low
    if fib_range > 0:
        for level in (0.5, 0.618):
            if direction == "LONG":
                fib_price = swing_high - fib_range * level
            else:
                fib_price = swing_low + fib_range * level
            if abs(current_price - fib_price) / current_price < config.FIB_TOLERANCE:
                confluences.append(f"FIB_{int(level*1000)/10}%")
                break

    # 2. FVG en/cerca del OB
    fvgs = detect_fvg(df_15m, direction)
    if fvgs and ob_data:
        for fvg in fvgs:
            if (fvg["low"] <= ob_data["high"] and fvg["high"] >= ob_data["low"]):
                confluences.append("FVG+OB")
                break

    # 3. Bollinger
    bb_lower = last.get("bb_lower", 0)
    bb_upper = last.get("bb_upper", 0)
    if direction == "LONG":
        # Cerca de banda inferior
        if current_price <= bb_lower * (1 + config.BB_LOWER_PROXIMITY):
            confluences.append("BOLL_DN")
        # Bloqueo: nunca LONG si está en BOLL UP
        if current_price >= bb_upper * (1 - config.BB_UPPER_PROXIMITY):
            return FilterResult(
                5, "Confluencias", False, False,
                "BLOQUEO: precio en BOLL UP (no LONG)",
            )
    else:
        if current_price >= bb_upper * (1 - config.BB_UPPER_PROXIMITY):
            confluences.append("BOLL_UP")
        if current_price <= bb_lower * (1 + config.BB_LOWER_PROXIMITY):
            return FilterResult(
                5, "Confluencias", False, False,
                "BLOQUEO: precio en BOLL DN (no SHORT)",
            )

    # 4. Supertrend como soporte/resistencia
    st_value = last.get("supertrend", 0)
    if st_value > 0 and abs(current_price - st_value) / current_price < 0.01:
        confluences.append("ST_S/R")

    # 5. BOS/CHoCH
    if detect_bos_choch(df_15m, direction):
        confluences.append("BOS/CHoCH")

    passed = len(confluences) >= config.MIN_CONFLUENCES
    return FilterResult(
        5, "Confluencias", passed, False,
        f"{len(confluences)}/5 confluencias: {', '.join(confluences)}",
        {"confluences": confluences, "count": len(confluences)},
    )


def detect_fvg(df: pd.DataFrame, direction: Direction, lookback: int = 30) -> List[Dict]:
    """
    Fair Value Gap:
      - Bullish: low[i+2] > high[i]  (gap entre velas i y i+2)
      - Bearish: high[i+2] < low[i]
    """
    fvgs = []
    if len(df) < lookback:
        return fvgs
    sub = df.iloc[-lookback:].reset_index(drop=True)
    for i in range(len(sub) - 2):
        c1, c3 = sub.iloc[i], sub.iloc[i + 2]
        if direction == "LONG" and c3["low"] > c1["high"]:
            gap = (c3["low"] - c1["high"]) / c1["high"]
            if gap > config.FVG_MIN_SIZE_PCT:
                fvgs.append({"low": float(c1["high"]), "high": float(c3["low"]), "type": "bullish"})
        elif direction == "SHORT" and c3["high"] < c1["low"]:
            gap = (c1["low"] - c3["high"]) / c1["low"]
            if gap > config.FVG_MIN_SIZE_PCT:
                fvgs.append({"low": float(c3["high"]), "high": float(c1["low"]), "type": "bearish"})
    return fvgs


def detect_bos_choch(df: pd.DataFrame, direction: Direction, lookback: int = 20) -> bool:
    """
    BOS (Break of Structure): rompe high/low previo en la dirección de la tendencia.
    """
    if len(df) < lookback + 5:
        return False
    sub = df.iloc[-lookback:].copy()
    if direction == "LONG":
        prior_high = sub.iloc[:-3]["high"].max()
        recent_high = sub.iloc[-3:]["high"].max()
        return recent_high > prior_high * 1.0005
    prior_low = sub.iloc[:-3]["low"].min()
    recent_low = sub.iloc[-3:]["low"].min()
    return recent_low < prior_low * 0.9995


# ==========================================================================
# FILTRO 6 - VOLUMEN INSTITUCIONAL
# ==========================================================================
def filter_6_volume(
    df_15m: pd.DataFrame,
    sweep_idx: Optional[int] = None,
) -> FilterResult:
    """
    - Vela del sweep: volumen > 1.5x MA(10)
    - Pullback al OB: volumen decreciente
    """
    if "vol_ma_10" not in df_15m.columns:
        return FilterResult(6, "Volumen", False, False, "Datos de volumen ausentes")

    last_5 = df_15m.iloc[-5:]
    sweep_candles = df_15m.iloc[-config.SWEEP_LOOKBACK:]

    # Buscar vela con volumen anómalo en el sweep
    high_vol = sweep_candles[
        sweep_candles["volume"] > sweep_candles["vol_ma_10"] * config.VOL_SWEEP_MULTIPLIER
    ]
    if high_vol.empty:
        return FilterResult(
            6, "Volumen", False, False,
            f"Sin vela con volumen >{config.VOL_SWEEP_MULTIPLIER}x MA(10)",
            {"reduce_size": True},  # Reducir tamaño 50% según regla
        )

    # Volumen decreciente en últimas velas (pullback saludable)
    vol_trend = last_5["volume"].iloc[-1] < last_5["volume"].iloc[-3]
    return FilterResult(
        6, "Volumen", True, False,
        f"Vol sweep válido, pullback {'saludable' if vol_trend else 'plano'}",
        {"vol_decreasing": bool(vol_trend)},
    )


# ==========================================================================
# FILTRO 7 - RISK/REWARD >= 1:2
# ==========================================================================
def filter_7_risk_reward(
    direction: Direction,
    entry: float,
    stop_loss: float,
    tp1: float,
    tp2: float,
) -> FilterResult:
    """
    Verifica:
      - SL <= 1.5% del entry
      - TP1 >= 2x distancia SL
      - Entry < TP1 (LONG) o Entry > TP1 (SHORT)
    """
    sl_distance = abs(entry - stop_loss)
    sl_pct = sl_distance / entry

    if sl_pct > config.RISK.max_sl_pct:
        return FilterResult(
            7, "Risk/Reward", False, True,
            f"SL = {sl_pct*100:.2f}% > máximo {config.RISK.max_sl_pct*100}%",
        )

    tp1_distance = abs(tp1 - entry)
    rr = tp1_distance / sl_distance if sl_distance > 0 else 0

    if rr < config.RISK.tp1_rr_min:
        return FilterResult(
            7, "Risk/Reward", False, True,
            f"R:R = 1:{rr:.2f} < mínimo 1:{config.RISK.tp1_rr_min}",
        )

    # Validar dirección
    if direction == "LONG" and entry >= tp1:
        return FilterResult(7, "Risk/Reward", False, True, "Entrada >= TP1 en LONG")
    if direction == "SHORT" and entry <= tp1:
        return FilterResult(7, "Risk/Reward", False, True, "Entrada <= TP1 en SHORT")

    return FilterResult(
        7, "Risk/Reward", True, True,
        f"R:R 1:{rr:.2f} (SL {sl_pct*100:.2f}%)",
        {"rr": float(rr), "sl_pct": float(sl_pct)},
    )


# ==========================================================================
# ORQUESTADOR PRINCIPAL
# ==========================================================================
def run_all_filters(
    direction: Direction,
    symbol: str,
    df_15m: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_4h: pd.DataFrame,
) -> FilterReport:
    """
    Ejecuta los 7 filtros en orden.
    Cortocircuita en filtros críticos (1, 2, 4, 7).
    """
    report = FilterReport(direction=direction, symbol=symbol)
    current_price = float(df_15m["close"].iloc[-1])
    report.entry_price = current_price

    # Filtro 1
    r1 = filter_1_macro_trend(direction, df_15m, df_1h, df_4h)
    report.results.append(r1)
    if not r1.passed:
        return report

    # Filtro 2
    r2 = filter_2_liquidity_sweep(direction, df_15m)
    report.results.append(r2)
    if not r2.passed:
        return report
    sweep_data = r2.data

    # Filtro 3
    r3 = filter_3_order_block(direction, df_15m, current_price)
    report.results.append(r3)
    ob_data = r3.data.get("ob") if r3.passed else None
    if r3.passed:
        report.entry_price = r3.data.get("entry", current_price)

    # Filtro 4
    r4 = filter_4_rsi(direction, df_15m, df_1h, df_4h)
    report.results.append(r4)
    if not r4.passed:
        return report

    # Calcular SL/TP basado en sweep + OB
    if direction == "LONG":
        sl_anchor = sweep_data.get("sweep_low", df_15m["low"].iloc[-config.SWEEP_LOOKBACK:].min())
        report.stop_loss = sl_anchor * 0.998  # margen
        sl_dist = report.entry_price - report.stop_loss
        report.tp1 = report.entry_price + sl_dist * 2.0
        report.tp2 = report.entry_price + sl_dist * 3.5
        report.tp3 = report.entry_price + sl_dist * 5.0
    else:
        sl_anchor = sweep_data.get("sweep_high", df_15m["high"].iloc[-config.SWEEP_LOOKBACK:].max())
        report.stop_loss = sl_anchor * 1.002
        sl_dist = report.stop_loss - report.entry_price
        report.tp1 = report.entry_price - sl_dist * 2.0
        report.tp2 = report.entry_price - sl_dist * 3.5
        report.tp3 = report.entry_price - sl_dist * 5.0

    # Filtro 5
    swing_high = float(df_15m["high"].iloc[-50:].max())
    swing_low = float(df_15m["low"].iloc[-50:].min())
    r5 = filter_5_confluences(
        direction, df_15m, ob_data, sweep_data, swing_high, swing_low, current_price
    )
    report.results.append(r5)
    report.confluences = r5.data.get("confluences", [])

    # Filtro 6
    r6 = filter_6_volume(df_15m)
    report.results.append(r6)

    # Filtro 7
    r7 = filter_7_risk_reward(
        direction, report.entry_price, report.stop_loss, report.tp1, report.tp2
    )
    report.results.append(r7)

    return report
