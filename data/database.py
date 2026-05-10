"""
data/database.py
================
Persistencia de trades con SQLite.
Tablas:
  - trades: registro de operaciones abiertas/cerradas
  - performance: métricas agregadas por día
"""

from __future__ import annotations
import sqlite3
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from threading import Lock
from pathlib import Path

logger = logging.getLogger(__name__)


class TradeDatabase:
    """SQLite-based trade logger."""

    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._lock = Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    tp1 REAL NOT NULL,
                    tp2 REAL NOT NULL,
                    tp3 REAL NOT NULL,
                    score REAL NOT NULL,
                    size_pct REAL NOT NULL,
                    confluences TEXT,
                    filters_passed TEXT,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    close_price REAL,
                    pnl REAL,
                    pnl_pct REAL,
                    close_reason TEXT,
                    status TEXT DEFAULT 'OPEN'
                );

                CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
                CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
                CREATE INDEX IF NOT EXISTS idx_trades_opened ON trades(opened_at);
            """)

    # ------------------------------------------------------------------
    # OPERACIONES
    # ------------------------------------------------------------------
    def log_trade_open(self, report, score: float, quantity: float, size_pct: float) -> int:
        """Inserta un trade abierto. Retorna ID del trade."""
        now = datetime.now(timezone.utc).isoformat()
        passed = ",".join(str(f) for f in report.passed_filters)
        confluences = ",".join(report.confluences)

        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO trades (
                    symbol, direction, quantity, entry_price,
                    stop_loss, tp1, tp2, tp3,
                    score, size_pct, confluences, filters_passed, opened_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    report.symbol, report.direction, quantity, report.entry_price,
                    report.stop_loss, report.tp1, report.tp2, report.tp3,
                    score, size_pct, confluences, passed, now,
                ),
            )
            conn.commit()
            return cur.lastrowid

    def log_trade_close(
        self,
        trade_id: int,
        close_price: float,
        pnl: float,
        pnl_pct: float,
        reason: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """UPDATE trades SET
                    closed_at=?, close_price=?, pnl=?, pnl_pct=?, close_reason=?, status='CLOSED'
                   WHERE id=?""",
                (now, close_price, pnl, pnl_pct, reason, trade_id),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # CONSULTAS
    # ------------------------------------------------------------------
    def get_open_trades(self) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM trades WHERE status='OPEN'").fetchall()
            return [dict(r) for r in rows]

    def get_pnl_since(self, since: datetime) -> float:
        """Suma de PnL realizado desde `since`."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl), 0) AS total FROM trades WHERE closed_at >= ?",
                (since.isoformat(),),
            ).fetchone()
            return float(row["total"] or 0)

    def get_stats(self) -> Dict[str, Any]:
        """Estadísticas globales: win rate, profit factor, total."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT pnl FROM trades WHERE status='CLOSED' AND pnl IS NOT NULL"
            ).fetchall()
            pnls = [r["pnl"] for r in rows]

        if not pnls:
            return {"trades": 0, "win_rate": 0, "profit_factor": 0, "net_pnl": 0}

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        return {
            "trades": len(pnls),
            "win_rate": len(wins) / len(pnls),
            "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
            "net_pnl": sum(pnls),
            "avg_win": (gross_profit / len(wins)) if wins else 0,
            "avg_loss": (gross_loss / len(losses)) if losses else 0,
        }
