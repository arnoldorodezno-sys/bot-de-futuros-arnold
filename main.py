"""
main.py
=======
Loop principal del bot de trading SMC.
- Inicializa todos los componentes
- Programa evaluación periódica con APScheduler
- Maneja shutdown limpio (Ctrl+C, SIGTERM)
- Reconexión automática y persistencia de estado
"""

from __future__ import annotations
import logging
import logging.handlers
import signal
import sys
import time
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import config
from exchange.binance_client import BinanceClient
from exchange.order_manager import OrderManager
from exchange.position_tracker import PositionTracker
from data.candle_fetcher import CandleFetcher
from data.multi_tf_analyzer import MultiTFAnalyzer
from data.database import TradeDatabase
from strategy.filter_engine import run_all_filters
from strategy.scoring_system import calculate_score, score_to_size_pct
from strategy.risk_manager import RiskManager
from notifications.telegram_bot import TelegramNotifier


# ==========================================================================
# LOGGING SETUP
# ==========================================================================
def setup_logging() -> logging.Logger:
    """Configura logging a archivo rotativo + consola."""
    Path("logs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, config.LOG_LEVEL))

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Archivo rotativo (10MB x 5)
    fh = logging.handlers.RotatingFileHandler(
        config.LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=5
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Consola
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger


# ==========================================================================
# BOT PRINCIPAL
# ==========================================================================
class TradingBot:
    """Orquesta todos los componentes del bot."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.running = False
        self.scheduler = BackgroundScheduler(timezone="UTC")

        # Validar configuración
        config.validate_config()

        # Componentes
        self.client = BinanceClient(
            api_key=config.BINANCE_API_KEY,
            api_secret=config.BINANCE_API_SECRET,
            testnet=config.TESTNET,
        )
        self.fetcher = CandleFetcher(self.client)
        self.analyzer = MultiTFAnalyzer(self.fetcher)
        self.db = TradeDatabase(config.DB_PATH)
        self.position_tracker = PositionTracker(self.client)
        self.order_manager = OrderManager(self.client, dry_run=config.DRY_RUN)
        self.risk_manager = RiskManager(self.client, self.db)
        self.notifier = TelegramNotifier(
            config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID
        )

        self._load_state()

    # ------------------------------------------------------------------
    # ESTADO PERSISTENTE
    # ------------------------------------------------------------------
    def _load_state(self) -> None:
        """Carga estado guardado para reanudación tras reinicio."""
        if not os.path.exists(config.STATE_FILE):
            self.state = {"last_run": None, "consecutive_errors": 0}
            return
        try:
            with open(config.STATE_FILE, "r") as f:
                self.state = json.load(f)
            self.logger.info(f"Estado cargado: {self.state}")
        except Exception as e:
            self.logger.warning(f"No se pudo cargar estado: {e}")
            self.state = {"last_run": None, "consecutive_errors": 0}

    def _save_state(self) -> None:
        try:
            with open(config.STATE_FILE, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            self.logger.warning(f"No se pudo guardar estado: {e}")

    # ------------------------------------------------------------------
    # LOOP DE EVALUACIÓN
    # ------------------------------------------------------------------
    def evaluate_symbol(self, symbol: str) -> None:
        """Evalúa un símbolo: descarga datos, corre filtros, ejecuta si procede."""
        try:
            self.logger.info(f"--- Evaluando {symbol} ---")

            # 0. Verificar límites globales (drawdown, posiciones abiertas)
            if not self.risk_manager.can_open_new_position():
                self.logger.info("Risk manager bloquea: drawdown / posiciones / cooldown")
                return

            # 1. Descargar y enriquecer datos multi-TF
            data = self.analyzer.get_enriched_dataframes(symbol)
            if not data:
                self.logger.warning(f"Datos insuficientes para {symbol}")
                return
            df_15m, df_1h, df_4h = data["15m"], data["1h"], data["4h"]

            # 2. Probar ambas direcciones
            for direction in ("LONG", "SHORT"):
                report = run_all_filters(direction, symbol, df_15m, df_1h, df_4h)
                score = calculate_score(report)

                summary = (
                    f"{symbol} {direction}: score={score:.1f} "
                    f"passed={report.passed_filters} crit_failed={report.critical_failed}"
                )

                if score < config.SCORE_MIN_TO_TRADE:
                    self.logger.debug(summary + " → descarte")
                    continue

                self.logger.info(summary + " → CANDIDATO")

                # 3. Verificar si ya existe posición en este símbolo
                if self.position_tracker.has_position(symbol):
                    self.logger.info(f"{symbol} ya tiene posición abierta, skip")
                    continue

                # 4. Calcular tamaño según score y volumen
                size_pct = score_to_size_pct(score)
                # Filtro 6 puede pedir reducir tamaño 50%
                vol_filter = next((r for r in report.results if r.filter_id == 6), None)
                if vol_filter and not vol_filter.passed and vol_filter.data.get("reduce_size"):
                    size_pct *= 0.5
                    self.logger.info("Tamaño reducido 50% por volumen débil")

                # 5. Ejecutar
                self._execute_trade(report, score, size_pct)
                break  # Solo una dirección por símbolo por ciclo

            self.state["consecutive_errors"] = 0

        except Exception as e:
            self.logger.exception(f"Error evaluando {symbol}: {e}")
            self.state["consecutive_errors"] = self.state.get("consecutive_errors", 0) + 1
            if self.state["consecutive_errors"] > 10:
                self.notifier.send_alert(f"⚠️ {self.state['consecutive_errors']} errores seguidos")

    def _execute_trade(self, report, score: float, size_pct: float) -> None:
        """Ejecuta la operación con SL/TPs escalonados."""
        capital = self.risk_manager.get_available_capital()
        position_value = capital * size_pct
        quantity = self.order_manager.calculate_quantity(
            report.symbol, position_value, report.entry_price
        )

        result = self.order_manager.open_position(
            symbol=report.symbol,
            direction=report.direction,
            quantity=quantity,
            entry_price=report.entry_price,
            stop_loss=report.stop_loss,
            tp1=report.tp1,
            tp2=report.tp2,
            tp3=report.tp3,
            leverage=config.RISK.leverage,
        )

        if result.get("success"):
            self.db.log_trade_open(report, score, quantity, size_pct)
            self.notifier.send_trade_open(report, score, size_pct)
            self.logger.info(f"✅ {report.direction} abierto en {report.symbol}")
        else:
            self.logger.error(f"Falló apertura: {result.get('error')}")

    def evaluate_all(self) -> None:
        """Ciclo de evaluación sobre todos los símbolos configurados."""
        self.state["last_run"] = datetime.now(timezone.utc).isoformat()
        for symbol in config.SYMBOLS:
            self.evaluate_symbol(symbol)
        self._save_state()

    def manage_open_positions(self) -> None:
        """Gestión de posiciones abiertas: trailing, cierre por TP, etc."""
        try:
            self.position_tracker.update_all()
            for pos in self.position_tracker.get_open_positions():
                self.risk_manager.manage_trailing(pos)
        except Exception as e:
            self.logger.exception(f"Error gestionando posiciones: {e}")

    # ------------------------------------------------------------------
    # CICLO DE VIDA
    # ------------------------------------------------------------------
    def start(self) -> None:
        self.logger.info("=" * 60)
        self.logger.info("BOT SMC ARRANCANDO")
        self.logger.info(f"  TESTNET={config.TESTNET}  DRY_RUN={config.DRY_RUN}  PAPER={config.PAPER_TRADING}")
        self.logger.info(f"  Símbolos: {config.SYMBOLS}")
        self.logger.info(f"  Loop cada {config.LOOP_INTERVAL_SECONDS}s")
        self.logger.info("=" * 60)

        self.running = True

        # Schedule evaluación principal
        self.scheduler.add_job(
            self.evaluate_all,
            IntervalTrigger(seconds=config.LOOP_INTERVAL_SECONDS),
            id="evaluate_all",
            max_instances=1,
            coalesce=True,
        )
        # Gestión de posiciones más frecuente
        self.scheduler.add_job(
            self.manage_open_positions,
            IntervalTrigger(seconds=15),
            id="manage_positions",
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.start()
        self.notifier.send_alert("🚀 Bot SMC iniciado")

        # Mantener vivo el proceso principal
        try:
            while self.running:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            self.stop()

    def stop(self) -> None:
        self.logger.info("Apagando bot...")
        self.running = False
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass
        self._save_state()
        self.notifier.send_alert("🛑 Bot SMC detenido")
        self.logger.info("Bot detenido limpiamente")


# ==========================================================================
# ENTRY POINT
# ==========================================================================
def handle_signal(signum, frame):
    logging.getLogger().info(f"Señal {signum} recibida, deteniendo...")
    if bot:
        bot.stop()
    sys.exit(0)


bot: Optional[TradingBot] = None

if __name__ == "__main__":
    setup_logging()
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    bot = TradingBot()
    try:
        bot.start()
    except Exception as e:
        logging.getLogger().exception(f"Error fatal: {e}")
        if bot:
            bot.stop()
        sys.exit(1)
