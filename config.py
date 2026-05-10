"""
config.py
=========
Configuración central del bot de trading SMC.
Todos los parámetros probados se centralizan aquí para facilitar tuning.
Las API keys NUNCA viven aquí, viven en .env (ver .env.example).
"""

import os
from dataclasses import dataclass, field
from typing import List, Tuple
from dotenv import load_dotenv

load_dotenv()

# ==========================================================================
# MODO DE EJECUCIÓN
# ==========================================================================
TESTNET: bool = os.getenv("TESTNET", "true").lower() == "true"
DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"  # Simula sin enviar órdenes
PAPER_TRADING: bool = os.getenv("PAPER_TRADING", "true").lower() == "true"

# ==========================================================================
# CREDENCIALES (cargadas desde .env)
# ==========================================================================
BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ==========================================================================
# PARES Y TIMEFRAMES
# ==========================================================================
SYMBOLS: List[str] = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "XRPUSDT"]
TIMEFRAMES: List[str] = ["15m", "1h", "4h"]
EXECUTION_TF: str = "15m"  # Timeframe base de ejecución
LOOP_INTERVAL_SECONDS: int = 60  # Cada cuánto evalúa el bot

# ==========================================================================
# PARÁMETROS DE INDICADORES (PROBADOS)
# ==========================================================================

# --- EMAs ---
EMA_FAST: int = 7
EMA_MID: int = 25
EMA_SLOW: int = 99

# --- Supertrend ---
SUPERTREND_PERIOD: int = 10
SUPERTREND_MULTIPLIER: float = 3.0

# --- Bollinger Bands ---
BB_PERIOD: int = 20
BB_STD: float = 2.0
BB_UPPER_PROXIMITY: float = 0.02  # 2% margen de "cerca de banda superior"
BB_LOWER_PROXIMITY: float = 0.02

# --- RSI ---
RSI_FAST: int = 6
RSI_SLOW: int = 14
RSI_LONG_MIN: float = 35.0
RSI_LONG_MAX: float = 60.0
RSI_SHORT_MIN: float = 40.0
RSI_SHORT_MAX: float = 65.0
RSI_FAST_LONG_BLOCK: float = 70.0   # Bloqueo LONG si RSI(6) > 70
RSI_FAST_SHORT_BLOCK: float = 30.0  # Bloqueo SHORT si RSI(6) < 30

# --- Volumen ---
VOL_MA_FAST: int = 5
VOL_MA_SLOW: int = 10
VOL_SWEEP_MULTIPLIER: float = 1.5  # Vela sweep > 1.5x MA(10)

# ==========================================================================
# PARÁMETROS SMC
# ==========================================================================
SWEEP_LOOKBACK: int = 8           # Buscar sweep en últimas N velas
OB_MAX_AGE_CANDLES: int = 50      # OB válido si tiene <50 velas
FVG_MIN_SIZE_PCT: float = 0.001   # FVG mínimo 0.1% del precio
FIB_LEVELS: Tuple[float, ...] = (0.382, 0.5, 0.618, 0.786)
FIB_TOLERANCE: float = 0.005      # 0.5% de tolerancia para "estar en el nivel"

# ==========================================================================
# GESTIÓN DE RIESGO
# ==========================================================================

@dataclass
class RiskConfig:
    """Configuración de gestión de riesgo."""
    # Tamaño por score
    size_score_perfect: float = 0.02   # 2% capital (score 9-10)
    size_score_good: float = 0.015     # 1.5% capital (score 7-8)
    size_score_weak: float = 0.01      # 1% capital (score 5-6)

    # Stops y targets
    max_sl_pct: float = 0.015          # SL máximo 1.5% desde entry
    tp1_rr_min: float = 2.0            # TP1 mínimo 2x distancia SL
    tp1_size_pct: float = 0.40         # TP1 cierra 40% posición
    tp2_size_pct: float = 0.40         # TP2 cierra 40% posición
    tp3_size_pct: float = 0.20         # TP3 trailing 20%

    # Límites operativos
    max_concurrent_positions: int = 4
    daily_drawdown_limit: float = 0.05   # 5% para parar el día
    weekly_drawdown_limit: float = 0.10  # 10% para revisar params
    leverage: int = 8                   # Apalancamiento por defecto

    # Cooldown
    cooldown_after_loss_seconds: int = 1800  # 30 min tras stop loss
    news_blackout_minutes: int = 30          # No operar 30min antes/después


RISK = RiskConfig()

# ==========================================================================
# SCORING (0-10)
# ==========================================================================
SCORE_PER_FILTER: float = 1.5         # +1.5 por filtro pasado (×7 = 10.5)
SCORE_MINOR_PENALTY: float = 0.5      # -0.5 por contradicción menor
SCORE_CRITICAL_PENALTY: float = 1.0   # -1.0 por filtro crítico fallido
CRITICAL_FILTERS: Tuple[int, ...] = (1, 2, 4, 7)  # Filtros críticos

SCORE_MIN_TO_TRADE: float = 5.0
SCORE_FULL_SIZE: float = 7.0
SCORE_PERFECT: float = 9.0

# ==========================================================================
# CONFLUENCIAS REQUERIDAS (Filtro 5)
# ==========================================================================
MIN_CONFLUENCES: int = 3   # Mínimo 3 de 5 confluencias

# ==========================================================================
# BACKTESTING
# ==========================================================================
BACKTEST_HISTORY_MONTHS: int = 6
COMMISSION_RATE: float = 0.0004     # 0.04% maker
SLIPPAGE: float = 0.0005            # 0.05% slippage estimado

# Métricas mínimas aceptables
WIN_RATE_MIN: float = 0.45
PROFIT_FACTOR_MIN: float = 1.5
MAX_DRAWDOWN_LIMIT: float = 0.20
SHARPE_TARGET: float = 1.5
MIN_TRADES_BACKTEST: int = 100

# ==========================================================================
# DATABASE Y LOGGING
# ==========================================================================
DB_PATH: str = "data/trades.db"
LOG_PATH: str = "logs/bot.log"
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
STATE_FILE: str = "data/bot_state.json"  # Persistencia para reinicios

# ==========================================================================
# VALIDACIÓN AL INICIO
# ==========================================================================
def validate_config() -> None:
    """Valida que la configuración tenga lo esencial."""
    if not DRY_RUN and not PAPER_TRADING:
        if not BINANCE_API_KEY or not BINANCE_API_SECRET:
            raise ValueError(
                "Modo LIVE activo pero faltan BINANCE_API_KEY/SECRET en .env"
            )
    if EMA_FAST >= EMA_MID or EMA_MID >= EMA_SLOW:
        raise ValueError("EMAs mal ordenadas: fast < mid < slow requerido")
    if RISK.tp1_size_pct + RISK.tp2_size_pct + RISK.tp3_size_pct != 1.0:
        raise ValueError("Suma de tamaños TP debe ser 100%")
