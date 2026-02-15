from __future__ import annotations

import aiosqlite


SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
    ts TEXT,
    market_slug TEXT,
    up_token_id TEXT,
    down_token_id TEXT,
    btc_price REAL,
    up_bid REAL,
    up_ask REAL,
    up_mid REAL,
    down_bid REAL,
    down_ask REAL,
    down_mid REAL,
    p_model REAL,
    p_up_mkt REAL,
    p_down_mkt REAL,
    edge_up REAL,
    edge_down REAL,
    decision TEXT,
    reason_code TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    market_slug TEXT,
    mode TEXT,
    token_id TEXT,
    side TEXT,
    limit_price REAL,
    size REAL,
    status TEXT,
    reason TEXT,
    created_ts TEXT,
    updated_ts TEXT
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT,
    ts TEXT,
    fill_price REAL,
    fill_size REAL
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_slug TEXT,
    token_id TEXT,
    entry_price REAL,
    size REAL,
    opened_ts TEXT,
    closed_ts TEXT,
    exit_reason TEXT
);
CREATE TABLE IF NOT EXISTS pnl (
    ts TEXT,
    realized REAL,
    unrealized REAL,
    exposure REAL
);
CREATE TABLE IF NOT EXISTS errors (
    ts TEXT,
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
        # lightweight migration from old MVP schema
        cur = await db.execute("PRAGMA table_info(orders)")
        cols = await cur.fetchall()
        if cols and len(cols) < 11:
            await db.execute("DROP TABLE IF EXISTS orders")
        cur = await db.execute("PRAGMA table_info(ticks)")
        cols = await cur.fetchall()
        if cols and len(cols) < 18:
            await db.execute("DROP TABLE IF EXISTS ticks")
        cur = await db.execute("PRAGMA table_info(fills)")
        cols = await cur.fetchall()
        if cols and (len(cols) < 5 or cols[3][1] != "fill_price"):
            await db.execute("DROP TABLE IF EXISTS fills")

    async def execute(self, sql: str, params: tuple = ()) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(sql, params)
            await db.commit()
