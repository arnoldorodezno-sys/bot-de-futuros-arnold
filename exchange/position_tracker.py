"""
exchange/position_tracker.py
============================
Tracker de posiciones abiertas:
  - Sincroniza estado con Binance
  - Detecta ejecución de TPs/SLs
  - Mantiene cache local para acceso rápido
"""

from __future__ import annotations
import logging
from typing import Dict, List, Any
from threading import Lock

logger = logging.getLogger(__name__)


class PositionTracker:
    """Mantiene estado de posiciones sincronizado con el exchange."""

    def __init__(self, client) -> None:
        self.client = client
        self._positions: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

    def update_all(self) -> None:
        """Sincroniza con Binance."""
        try:
            raw = self.client.get_open_positions()
            with self._lock:
                self._positions.clear()
                for p in raw:
                    amt = float(p.get("positionAmt", 0))
                    if abs(amt) < 1e-9:
                        continue
                    direction = "LONG" if amt > 0 else "SHORT"
                    self._positions[p["symbol"]] = {
                        "symbol": p["symbol"],
                        "direction": direction,
                        "quantity": abs(amt),
                        "entry_price": float(p.get("entryPrice", 0)),
                        "mark_price": float(p.get("markPrice", 0)),
                        "unrealized_pnl": float(p.get("unRealizedProfit", 0)),
                        "leverage": int(float(p.get("leverage", 1))),
                        "stop_loss": 0.0,  # se enriquece desde DB
                        "tp1_hit": False,
                    }
        except Exception as e:
            logger.error(f"Error actualizando posiciones: {e}")

    def has_position(self, symbol: str) -> bool:
        with self._lock:
            return symbol in self._positions

    def get_position(self, symbol: str) -> Dict[str, Any] | None:
        with self._lock:
            return self._positions.get(symbol)

    def get_open_positions(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._positions.values())

    def mark_tp1_hit(self, symbol: str) -> None:
        with self._lock:
            if symbol in self._positions:
                self._positions[symbol]["tp1_hit"] = True
