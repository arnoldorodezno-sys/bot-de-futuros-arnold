"""
strategy/scoring_system.py
==========================
Cálculo del score 0-10 para un setup, basado en filtros pasados.

Fórmula:
  +1.5 puntos por cada filtro PASA (×7 = 10.5 max)
  -0.5 por contradicciones menores
  -1.0 por filtros críticos fallidos (1, 2, 4, 7)
"""

import logging
import config
from strategy.filter_engine import FilterReport

logger = logging.getLogger(__name__)


def calculate_score(report: FilterReport) -> float:
    """
    Calcula score 0-10 para un FilterReport.

    Returns
    -------
    float
        Score entre 0 y 10. Si hay filtros críticos fallidos, score se penaliza.
    """
    score = 0.0
    for r in report.results:
        if r.passed:
            score += config.SCORE_PER_FILTER

    # Penalizaciones
    for filter_id in report.critical_failed:
        score -= config.SCORE_CRITICAL_PENALTY

    # Penalización menor por contradicciones (filtros no críticos fallidos)
    minor_failed = [
        r for r in report.results
        if not r.passed and r.filter_id not in config.CRITICAL_FILTERS
    ]
    score -= len(minor_failed) * config.SCORE_MINOR_PENALTY

    # Limitar a [0, 10]
    score = max(0.0, min(10.0, score))
    return round(score, 2)


def score_to_size_pct(score: float) -> float:
    """
    Mapea score a tamaño de posición:
      9-10  → 2.0% capital
      7-8   → 1.5% capital
      5-6   → 1.0% capital
      <5    → 0% (no operar)
    """
    if score >= config.SCORE_PERFECT:
        return config.RISK.size_score_perfect
    if score >= config.SCORE_FULL_SIZE:
        return config.RISK.size_score_good
    if score >= config.SCORE_MIN_TO_TRADE:
        return config.RISK.size_score_weak
    return 0.0


def score_label(score: float) -> str:
    """Etiqueta legible del score."""
    if score >= config.SCORE_PERFECT:
        return "PERFECTO"
    if score >= config.SCORE_FULL_SIZE:
        return "BUENO"
    if score >= config.SCORE_MIN_TO_TRADE:
        return "DÉBIL"
    return "INVÁLIDO"
