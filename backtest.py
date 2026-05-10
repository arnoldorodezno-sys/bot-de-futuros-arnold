"""
backtest.py
===========
Backtester para validar la estrategia antes de ir live.

Uso:
    python backtest.py --symbol ETHUSDT --months 6

Métricas reportadas:
  - Win rate
  - Profit factor
  - Max drawdown
  - Sharpe ratio
  - Número total de trades
"""

from __future__ import annotations
import argparse
import logging
import math
from datetime import datetime, timedelta
from typing import List, Dict, Any
import pandas as pd
import numpy as np

import config
from exchange.binance_client import BinanceClient
from data.candle_fetcher import CandleFetcher
from data.multi_tf_analyzer import MultiTFAnalyzer
from strategy.filter_engine import run_all_filters
from strategy.scoring_system import calculate_score, score_to_size_pct

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("backtest")


class Backtester:
    """Simulador de la estrategia sobre datos históricos."""

    def __init__(self, symbol: str, months: int = 6) -> None:
        self.symbol = symbol
        self.months = months
        self.client = BinanceClient(
            api_key=config.BINANCE_API_KEY,
            api_secret=config.BINANCE_API_SECRET,
            testnet=False,  # datos públicos, no necesita testnet
        )
        self.fetcher = CandleFetcher(self.client)
        self.analyzer = MultiTFAnalyzer(self.fetcher)

        self.initial_capital = 10_000.0
        self.equity = self.initial_capital
        self.trades: List[Dict[str, Any]] = []
        self.equity_curve: List[float] = [self.initial_capital]

    # ------------------------------------------------------------------
    # DESCARGA DE HISTORIAL
    # ------------------------------------------------------------------
    def _fetch_history(self) -> Dict[str, pd.DataFrame]:
        """Descarga historial completo en cada TF."""
        bars_per_tf = {
            "15m": min(self.months * 30 * 96, 1500),
            "1h": min(self.months * 30 * 24, 1500),
            "4h": min(self.months * 30 * 6, 1500),
        }
        out = {}
        for tf in config.TIMEFRAMES:
            df = self.fetcher.fetch(self.symbol, tf, limit=bars_per_tf[tf])
            if df is None:
                raise RuntimeError(f"No se pudo descargar historial {tf}")
            out[tf] = self.analyzer._enrich(df)
            logger.info(f"  {tf}: {len(df)} velas descargadas")
        return out

    # ------------------------------------------------------------------
    # SIMULACIÓN
    # ------------------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        logger.info(f"Backtest {self.symbol} - {self.months} meses")
        history = self._fetch_history()
        df_15m = history["15m"]
        df_1h = history["1h"]
        df_4h = history["4h"]

        # Iterar el TF de ejecución (15m), recortando hasta cada vela
        start_idx = 200  # warm-up para indicadores
        for i in range(start_idx, len(df_15m) - 1):
            slice_15m = df_15m.iloc[: i + 1]
            current_time = slice_15m["close_time"].iloc[-1]
            slice_1h = df_1h[df_1h["close_time"] <= current_time]
            slice_4h = df_4h[df_4h["close_time"] <= current_time]

            if len(slice_1h) < 100 or len(slice_4h) < 100:
                continue

            for direction in ("LONG", "SHORT"):
                report = run_all_filters(direction, self.symbol, slice_15m, slice_1h, slice_4h)
                score = calculate_score(report)
                if score < config.SCORE_MIN_TO_TRADE:
                    continue
                if not report.all_passed:
                    continue

                # Simular el trade contra los siguientes datos de 15m
                self._simulate_trade(report, score, df_15m, i)
                break

        self.equity_curve.append(self.equity)
        return self._compute_metrics()

    def _simulate_trade(self, report, score: float, df: pd.DataFrame, entry_idx: int) -> None:
        """Simula el trade hasta que toca SL, TP o el final del historial."""
        entry = report.entry_price
        sl = report.stop_loss
        tp1 = report.tp1
        tp2 = report.tp2
        size_pct = score_to_size_pct(score)
        risk_amount = self.equity * size_pct
        sl_distance = abs(entry - sl)
        if sl_distance == 0:
            return
        position_size = (risk_amount / sl_distance) * entry  # tamaño nominal

        # Aplicar slippage + comisión a la entrada
        entry_eff = entry * (1 + config.SLIPPAGE) if report.direction == "LONG" else entry * (1 - config.SLIPPAGE)

        future = df.iloc[entry_idx + 1: entry_idx + 200]
        outcome = None
        exit_price = entry
        for _, candle in future.iterrows():
            if report.direction == "LONG":
                if candle["low"] <= sl:
                    outcome = "SL"
                    exit_price = sl
                    break
                if candle["high"] >= tp2:
                    outcome = "TP2"
                    exit_price = tp2
                    break
                if candle["high"] >= tp1:
                    # Cierre parcial 40% en TP1, el resto a breakeven
                    pnl_partial = self._calc_pnl(entry_eff, tp1, position_size * 0.4, "LONG")
                    self.equity += pnl_partial
                    sl = entry  # mover a breakeven
            else:  # SHORT
                if candle["high"] >= sl:
                    outcome = "SL"
                    exit_price = sl
                    break
                if candle["low"] <= tp2:
                    outcome = "TP2"
                    exit_price = tp2
                    break
                if candle["low"] <= tp1:
                    pnl_partial = self._calc_pnl(entry_eff, tp1, position_size * 0.4, "SHORT")
                    self.equity += pnl_partial
                    sl = entry

        if outcome is None:
            outcome = "TIMEOUT"
            exit_price = future["close"].iloc[-1] if not future.empty else entry

        # Calcular PnL final del 60% restante (o 100% si no tocó TP1)
        remaining = position_size * 0.6 if "TP1" in str(outcome) else position_size
        pnl = self._calc_pnl(entry_eff, exit_price, remaining, report.direction)
        commission = position_size * config.COMMISSION_RATE * 2  # entry + exit
        pnl -= commission
        self.equity += pnl

        self.trades.append({
            "entry": entry_eff, "exit": exit_price, "direction": report.direction,
            "score": score, "pnl": pnl, "outcome": outcome,
        })
        self.equity_curve.append(self.equity)

    @staticmethod
    def _calc_pnl(entry: float, exit_price: float, size: float, direction: str) -> float:
        units = size / entry
        if direction == "LONG":
            return (exit_price - entry) * units
        return (entry - exit_price) * units

    # ------------------------------------------------------------------
    # MÉTRICAS
    # ------------------------------------------------------------------
    def _compute_metrics(self) -> Dict[str, Any]:
        if not self.trades:
            return {"trades": 0}

        pnls = [t["pnl"] for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))

        equity = np.array(self.equity_curve)
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak
        max_dd = abs(drawdown.min()) if len(drawdown) > 0 else 0

        returns = np.diff(equity) / equity[:-1] if len(equity) > 1 else np.array([0])
        sharpe = (returns.mean() / returns.std() * math.sqrt(252)) if returns.std() > 0 else 0

        return {
            "trades": len(self.trades),
            "win_rate": len(wins) / len(self.trades),
            "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
            "net_pnl": sum(pnls),
            "net_pnl_pct": (self.equity / self.initial_capital - 1) * 100,
            "max_drawdown": max_dd,
            "sharpe": sharpe,
            "final_equity": self.equity,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--months", type=int, default=6)
    args = parser.parse_args()

    bt = Backtester(args.symbol, args.months)
    metrics = bt.run()

    print("\n" + "=" * 50)
    print("RESULTADOS BACKTEST")
    print("=" * 50)
    print(f"Símbolo: {args.symbol}")
    print(f"Meses: {args.months}")
    print(f"Trades: {metrics['trades']}")
    if metrics["trades"] > 0:
        print(f"Win Rate: {metrics['win_rate']*100:.1f}% (mín. {config.WIN_RATE_MIN*100}%)")
        print(f"Profit Factor: {metrics['profit_factor']:.2f} (mín. {config.PROFIT_FACTOR_MIN})")
        print(f"Max Drawdown: {metrics['max_drawdown']*100:.1f}% (máx. {config.MAX_DRAWDOWN_LIMIT*100}%)")
        print(f"Sharpe: {metrics['sharpe']:.2f} (objetivo {config.SHARPE_TARGET})")
        print(f"PnL Neto: ${metrics['net_pnl']:.2f} ({metrics['net_pnl_pct']:.1f}%)")
        print(f"Equity Final: ${metrics['final_equity']:.2f}")
    print("=" * 50)


if __name__ == "__main__":
    main()
