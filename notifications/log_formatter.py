"""
notifications/log_formatter.py
==============================
Helpers para formatear reports y stats en strings legibles
(útiles tanto para logs como para Telegram).
"""

from __future__ import annotations
from typing import Dict, Any
from strategy.filter_engine import FilterReport


def format_filter_report(report: FilterReport, score: float) -> str:
    """Genera un resumen multi-línea del FilterReport."""
    lines = [
        f"=== {report.symbol} {report.direction} | score={score:.1f} ===",
        f"  Entry: {report.entry_price:.4f}  SL: {report.stop_loss:.4f}",
        f"  TP1: {report.tp1:.4f}  TP2: {report.tp2:.4f}  TP3: {report.tp3:.4f}",
        "  Filtros:",
    ]
    for r in report.results:
        icon = "✓" if r.passed else "✗"
        crit = " [CRÍTICO]" if r.critical and not r.passed else ""
        lines.append(f"    {icon} F{r.filter_id} {r.name}: {r.reason}{crit}")
    if report.confluences:
        lines.append(f"  Confluencias: {', '.join(report.confluences)}")
    return "\n".join(lines)


def format_stats(stats: Dict[str, Any]) -> str:
    """Resumen de estadísticas globales."""
    return (
        f"Trades: {stats['trades']} | "
        f"Win rate: {stats['win_rate']*100:.1f}% | "
        f"Profit Factor: {stats['profit_factor']:.2f} | "
        f"Net PnL: ${stats['net_pnl']:.2f}"
    )
