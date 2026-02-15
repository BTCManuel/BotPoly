from __future__ import annotations

import aiosqlite


SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    market_slug TEXT,
    token_id TEXT,
    side TEXT,
    price REAL,
    size REAL,
    status TEXT,
    reason TEXT,
    created_ts REAL,
    updated_ts REAL
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT,
    fill_price REAL,
    fill_size REAL,
    ts REAL
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id TEXT,
    entry_price REAL,
    size REAL,
    opened_ts REAL,
    closed_ts REAL,
    exit_reason TEXT
);
CREATE TABLE IF NOT EXISTS ticks (
    ts REAL,
    btc_price REAL,
    up_mid REAL,
    down_mid REAL,
    p_model REAL,
    decision TEXT,
    edge REAL,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS pnl (
    ts REAL,
    realized REAL,
    unrealized REAL
);
CREATE TABLE IF NOT EXISTS errors (
    ts REAL,
    source TEXT,
    message TEXT
);
"""


class Storage:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            await db.executescript(SCHEMA)
            await db.commit()

    async def _ensure_schema(self, db: aiosqlite.Connection) -> None:
        expected = {
            "orders": ["id", "market_slug", "token_id", "side", "price", "size", "status", "reason", "created_ts", "updated_ts"],
            "fills": ["id", "order_id", "fill_price", "fill_size", "ts"],
            "positions": ["id", "token_id", "entry_price", "size", "opened_ts", "closed_ts", "exit_reason"],
            "ticks": ["ts", "btc_price", "up_mid", "down_mid", "p_model", "decision", "edge", "reason"],
            "pnl": ["ts", "realized", "unrealized"],
        }
        for table, columns in expected.items():
            cur = await db.execute(f"PRAGMA table_info({table})")
            table_info = await cur.fetchall()
            if not table_info:
                continue
            existing = [row[1] for row in table_info]
            if existing != columns or len(existing) != len(set(existing)):
                await db.execute(f"DROP TABLE IF EXISTS {table}")

    async def execute(self, sql: str, params: tuple = ()) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(sql, params)
            await db.commit()
