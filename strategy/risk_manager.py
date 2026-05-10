"""
strategy/risk_manager.py
========================
Gestión de riesgo:
  - Verifica límites de drawdown diario/semanal
  - Limita número de posiciones simultáneas
  - Maneja trailing stops post-TP1
  - Cooldown tras stop loss
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
import config

logger = logging.getLogger(__name__)


class RiskManager:
    """Centraliza decisiones de riesgo."""

    def __init__(self, client, db) -> None:
        self.client = client
        self.db = db
        self.last_loss_time: datetime | None = None

    # ------------------------------------------------------------------
    # CAPITAL
    # ------------------------------------------------------------------
    def get_available_capital(self) -> float:
        """Retorna balance USDT disponible en futuros."""
        try:
            balance = self.client.get_futures_balance()
            return float(balance.get("availableBalance", 0))
        except Exception as e:
            logger.error(f"Error obteniendo balance: {e}")
            return 0.0

    def get_total_balance(self) -> float:
        """Retorna balance total (incluyendo posiciones abiertas)."""
        try:
            balance = self.client.get_futures_balance()
            return float(balance.get("totalWalletBalance", 0))
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # CHECKS PRE-TRADE
    # ------------------------------------------------------------------
    def can_open_new_position(self) -> bool:
        """
        Verifica todos los gatekeepers:
          - Drawdown diario/semanal
          - Posiciones abiertas < máximo
          - Cooldown tras pérdida
        """
        if self._exceeds_daily_drawdown():
            logger.warning("Drawdown diario excedido, bloqueando nuevas operaciones")
            return False
        if self._exceeds_weekly_drawdown():
            logger.warning("Drawdown semanal excedido, revisar parámetros")
            return False
        if self._too_many_positions():
            logger.info(f"Máximo de {config.RISK.max_concurrent_positions} posiciones alcanzado")
            return False
        if self._in_cooldown():
            logger.info("En cooldown post-pérdida")
            return False
        return True

    def _exceeds_daily_drawdown(self) -> bool:
        today_pnl = self.db.get_pnl_since(datetime.now(timezone.utc) - timedelta(days=1))
        balance = self.get_total_balance()
        if balance <= 0:
            return False
        return (today_pnl / balance) <= -config.RISK.daily_drawdown_limit

    def _exceeds_weekly_drawdown(self) -> bool:
        week_pnl = self.db.get_pnl_since(datetime.now(timezone.utc) - timedelta(days=7))
        balance = self.get_total_balance()
        if balance <= 0:
            return False
        return (week_pnl / balance) <= -config.RISK.weekly_drawdown_limit

    def _too_many_positions(self) -> bool:
        try:
            positions = self.client.get_open_positions()
            active = [p for p in positions if abs(float(p.get("positionAmt", 0))) > 0]
            return len(active) >= config.RISK.max_concurrent_positions
        except Exception as e:
            logger.error(f"Error contando posiciones: {e}")
            return True  # Fail safe: si no podemos verificar, no operamos

    def _in_cooldown(self) -> bool:
        if not self.last_loss_time:
            return False
        elapsed = (datetime.now(timezone.utc) - self.last_loss_time).total_seconds()
        return elapsed < config.RISK.cooldown_after_loss_seconds

    def register_loss(self) -> None:
        """Marca timestamp de pérdida para iniciar cooldown."""
        self.last_loss_time = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # TRAILING STOP POST-TP1
    # ------------------------------------------------------------------
    def manage_trailing(self, position: Dict[str, Any]) -> None:
        """
        Si TP1 ya tocó, mover SL a breakeven y activar trailing.
        """
        if not position.get("tp1_hit"):
            return

        symbol = position["symbol"]
        direction = position["direction"]
        entry = position["entry_price"]
        current = position["mark_price"]
        current_sl = position["stop_loss"]

        # Si SL aún no está en breakeven, moverlo
        if direction == "LONG":
            if current_sl < entry:
                new_sl = entry * 1.0005  # breakeven + pequeño margen
                self._update_stop_loss(symbol, direction, new_sl)
                logger.info(f"{symbol}: SL movido a breakeven {new_sl:.4f}")
            else:
                # Trailing: SL = max(SL_actual, precio - 1%)
                trailing = current * 0.99
                if trailing > current_sl:
                    self._update_stop_loss(symbol, direction, trailing)
        else:  # SHORT
            if current_sl > entry:
                new_sl = entry * 0.9995
                self._update_stop_loss(symbol, direction, new_sl)
            else:
                trailing = current * 1.01
                if trailing < current_sl:
                    self._update_stop_loss(symbol, direction, trailing)

    def _update_stop_loss(self, symbol: str, direction: str, new_sl: float) -> None:
        """Actualiza SL en el exchange."""
        try:
            self.client.update_stop_loss(symbol, direction, new_sl)
        except Exception as e:
            logger.error(f"No se pudo actualizar SL: {e}")
