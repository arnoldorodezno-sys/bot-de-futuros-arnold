"""
notifications/telegram_bot.py
=============================
Envío de alertas a Telegram vía API HTTP simple.
No-op si TELEGRAM_BOT_TOKEN no está configurado.
"""

from __future__ import annotations
import logging
import requests
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Cliente Telegram sencillo basado en requests."""

    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        if not self.enabled:
            logger.info("Telegram desactivado (faltan credenciales)")

    def _send(self, text: str) -> None:
        if not self.enabled:
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"Error enviando a Telegram: {e}")

    # ------------------------------------------------------------------
    # MENSAJES
    # ------------------------------------------------------------------
    def send_alert(self, text: str) -> None:
        self._send(text)

    def send_trade_open(self, report, score: float, size_pct: float) -> None:
        emoji = "🟢" if report.direction == "LONG" else "🔴"
        sl_pct = abs(report.entry_price - report.stop_loss) / report.entry_price * 100
        tp1_pct = abs(report.tp1 - report.entry_price) / report.entry_price * 100
        tp2_pct = abs(report.tp2 - report.entry_price) / report.entry_price * 100
        rr1 = abs(report.tp1 - report.entry_price) / abs(report.entry_price - report.stop_loss)
        rr2 = abs(report.tp2 - report.entry_price) / abs(report.entry_price - report.stop_loss)
        passed = "".join(_circled(f) for f in report.passed_filters)

        msg = (
            f"{emoji} <b>{report.direction} ABIERTO</b> | {report.symbol}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 Score: <b>{score:.1f}/10</b>\n"
            f"💰 Entry: ${report.entry_price:,.2f}\n"
            f"🛑 SL: ${report.stop_loss:,.2f} (-{sl_pct:.2f}%)\n"
            f"🎯 TP1: ${report.tp1:,.2f} (+{tp1_pct:.2f}%)\n"
            f"🎯 TP2: ${report.tp2:,.2f} (+{tp2_pct:.2f}%)\n"
            f"📐 R:R → 1:{rr1:.1f} / 1:{rr2:.1f}\n"
            f"💼 Tamaño: {size_pct*100:.1f}% capital\n"
            f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Filtros pasados: {passed}\n"
            f"Confluencias: {'+'.join(report.confluences) if report.confluences else 'N/A'}"
        )
        self._send(msg)

    def send_trade_close(self, symbol: str, direction: str, pnl: float, pnl_pct: float, reason: str) -> None:
        emoji = "✅" if pnl > 0 else "❌"
        msg = (
            f"{emoji} <b>POSICIÓN CERRADA</b> | {symbol} {direction}\n"
            f"PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)\n"
            f"Motivo: {reason}"
        )
        self._send(msg)


def _circled(num: int) -> str:
    """Convierte número a su versión 'circled' Unicode (1→①, 2→②, etc)."""
    table = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤", 6: "⑥", 7: "⑦"}
    return table.get(num, str(num))
