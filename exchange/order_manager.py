"""
exchange/order_manager.py
=========================
Gestión de órdenes:
  - Calcula tamaño de posición
  - Abre posición + SL + TPs escalonados (40/40/20)
  - Cierra posiciones
  - Soporta DRY_RUN para simular sin enviar nada
"""

from __future__ import annotations
import logging
import math
from typing import Dict, Any
import config

logger = logging.getLogger(__name__)


class OrderManager:
    """Gestiona el ciclo de vida de las órdenes."""

    def __init__(self, client, dry_run: bool = True) -> None:
        self.client = client
        self.dry_run = dry_run
        self._symbol_info_cache: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    # SYMBOL INFO (precision, mínimos)
    # ------------------------------------------------------------------
    def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """Cachea información del símbolo (step size, tick size)."""
        if symbol in self._symbol_info_cache:
            return self._symbol_info_cache[symbol]

        info = self.client.get_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                step = 0.001
                tick = 0.01
                min_qty = 0.001
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        step = float(f["stepSize"])
                        min_qty = float(f["minQty"])
                    elif f["filterType"] == "PRICE_FILTER":
                        tick = float(f["tickSize"])
                self._symbol_info_cache[symbol] = {
                    "step_size": step,
                    "tick_size": tick,
                    "min_qty": min_qty,
                }
                return self._symbol_info_cache[symbol]
        # Defaults razonables
        return {"step_size": 0.001, "tick_size": 0.01, "min_qty": 0.001}

    def calculate_quantity(self, symbol: str, position_value_usdt: float, price: float) -> float:
        """
        Calcula cantidad respetando step size y mínimos.
        position_value_usdt incluye el apalancamiento implícito vía RiskManager.
        """
        info = self.get_symbol_info(symbol)
        raw_qty = (position_value_usdt * config.RISK.leverage) / price
        # Redondear hacia abajo al step size
        step = info["step_size"]
        qty = math.floor(raw_qty / step) * step
        # Asegurar mínimo
        if qty < info["min_qty"]:
            logger.warning(f"{symbol}: cantidad {qty} < min {info['min_qty']}")
            return 0.0
        # Limpiar precisión
        decimals = max(0, -int(math.log10(step)))
        return round(qty, decimals)

    def round_price(self, symbol: str, price: float) -> float:
        info = self.get_symbol_info(symbol)
        tick = info["tick_size"]
        decimals = max(0, -int(math.log10(tick)))
        return round(round(price / tick) * tick, decimals)

    # ------------------------------------------------------------------
    # APERTURA DE POSICIÓN COMPLETA
    # ------------------------------------------------------------------
    def open_position(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        entry_price: float,
        stop_loss: float,
        tp1: float,
        tp2: float,
        tp3: float,
        leverage: int = 5,
    ) -> Dict[str, Any]:
        """
        Abre posición con orden de mercado + SL + 3 TPs escalonados.
        """
        if quantity <= 0:
            return {"success": False, "error": "Cantidad inválida"}

        side_open = "BUY" if direction == "LONG" else "SELL"
        side_close = "SELL" if direction == "LONG" else "BUY"

        sl_price = self.round_price(symbol, stop_loss)
        tp1_price = self.round_price(symbol, tp1)
        tp2_price = self.round_price(symbol, tp2)
        tp3_price = self.round_price(symbol, tp3)

        info = self.get_symbol_info(symbol)
        step = info["step_size"]
        decimals = max(0, -int(math.log10(step)))
        qty_tp1 = round(math.floor(quantity * config.RISK.tp1_size_pct / step) * step, decimals)
        qty_tp2 = round(math.floor(quantity * config.RISK.tp2_size_pct / step) * step, decimals)
        qty_tp3 = round(quantity - qty_tp1 - qty_tp2, decimals)

        if self.dry_run:
            logger.info(
                f"[DRY-RUN] {direction} {symbol} qty={quantity} entry≈{entry_price} "
                f"SL={sl_price} TP1={tp1_price}({qty_tp1}) TP2={tp2_price}({qty_tp2}) TP3={tp3_price}({qty_tp3})"
            )
            return {"success": True, "dry_run": True}

        try:
            # 1. Apalancamiento
            self.client.set_leverage(symbol, leverage)

            # 2. Orden de mercado
            entry_order = self.client.place_market_order(symbol, side_open, quantity)

            # 3. Stop Loss (cubre TODA la posición)
            self.client.place_stop_loss(symbol, side_close, sl_price, quantity)

            # 4. Take Profits escalonados
            if qty_tp1 > 0:
                self.client.place_take_profit(symbol, side_close, tp1_price, qty_tp1)
            if qty_tp2 > 0:
                self.client.place_take_profit(symbol, side_close, tp2_price, qty_tp2)
            if qty_tp3 > 0:
                self.client.place_take_profit(symbol, side_close, tp3_price, qty_tp3)

            return {"success": True, "order": entry_order}

        except Exception as e:
            logger.exception(f"Error abriendo posición: {e}")
            # Intentar limpiar órdenes parciales
            try:
                self.client.cancel_all_orders(symbol)
            except Exception:
                pass
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # CIERRE
    # ------------------------------------------------------------------
    def close_position(self, symbol: str, direction: str, quantity: float) -> Dict[str, Any]:
        """Cierra posición a mercado y cancela órdenes pendientes."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Cerrando {direction} {symbol} qty={quantity}")
            return {"success": True, "dry_run": True}

        side = "SELL" if direction == "LONG" else "BUY"
        try:
            order = self.client.place_market_order(symbol, side, quantity)
            self.client.cancel_all_orders(symbol)
            return {"success": True, "order": order}
        except Exception as e:
            logger.exception(f"Error cerrando posición: {e}")
            return {"success": False, "error": str(e)}
