from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(slots=True)
class SessionReport:
    total_orders: int
    buy_orders: int
    sell_orders: int
    fills_total: int
    open_positions: int
    closed_positions: int
    realized_pnl_usd: float


def _table_exists(cur: sqlite3.Cursor, table_name: str) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table_name,))
    return cur.fetchone() is not None


def build_session_report(db_path: str, mode: str) -> SessionReport:
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        total_orders = buy_orders = sell_orders = fills_total = 0
        open_positions = closed_positions = 0
        realized_pnl = 0.0

        if _table_exists(cur, "orders"):
            cur.execute("SELECT COUNT(*) FROM orders WHERE mode = ?", (mode,))
            total_orders = int(cur.fetchone()[0])

            cur.execute("SELECT COUNT(*) FROM orders WHERE mode = ? AND side = 'buy'", (mode,))
            buy_orders = int(cur.fetchone()[0])

            cur.execute("SELECT COUNT(*) FROM orders WHERE mode = ? AND side = 'sell'", (mode,))
            sell_orders = int(cur.fetchone()[0])

        if _table_exists(cur, "fills") and _table_exists(cur, "orders"):
            cur.execute(
                "SELECT COUNT(*) FROM fills WHERE order_id IN (SELECT id FROM orders WHERE mode = ?)",
                (mode,),
            )
            fills_total = int(cur.fetchone()[0])

        if _table_exists(cur, "positions"):
            cur.execute("SELECT COUNT(*) FROM positions WHERE closed_ts IS NULL")
            open_positions = int(cur.fetchone()[0])

            cur.execute("SELECT COUNT(*) FROM positions WHERE closed_ts IS NOT NULL")
            closed_positions = int(cur.fetchone()[0])

        if _table_exists(cur, "pnl"):
            cur.execute("SELECT realized FROM pnl ORDER BY ts DESC LIMIT 1")
            row = cur.fetchone()
            realized_pnl = float(row[0]) if row else 0.0

    return SessionReport(
        total_orders=total_orders,
        buy_orders=buy_orders,
        sell_orders=sell_orders,
        fills_total=fills_total,
        open_positions=open_positions,
        closed_positions=closed_positions,
        realized_pnl_usd=realized_pnl,
    )
