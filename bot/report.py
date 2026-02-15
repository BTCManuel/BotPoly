from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(slots=True)
class SessionReport:
    total_orders: int
    buy_orders: int
    sell_orders: int
    realized_pnl_usd: float
    open_buys: int


def build_session_report(db_path: str, mode: str) -> SessionReport:
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM orders WHERE mode = ?", (mode,))
        total_orders = int(cur.fetchone()[0])

        cur.execute("SELECT COUNT(*) FROM orders WHERE mode = ? AND side = 'buy'", (mode,))
        buy_orders = int(cur.fetchone()[0])

        cur.execute("SELECT COUNT(*) FROM orders WHERE mode = ? AND side = 'sell'", (mode,))
        sell_orders = int(cur.fetchone()[0])

        cur.execute("SELECT realized FROM pnl ORDER BY ts DESC LIMIT 1")
        row = cur.fetchone()
        realized_pnl = float(row[0]) if row else 0.0

        open_buys = max(buy_orders - sell_orders, 0)

    return SessionReport(
        total_orders=total_orders,
        buy_orders=buy_orders,
        sell_orders=sell_orders,
        realized_pnl_usd=realized_pnl,
        open_buys=open_buys,
    )
