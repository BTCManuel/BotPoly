from __future__ import annotations

import aiosqlite


SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
    ts TEXT,
    btc_price REAL,
    up_mid REAL,
    down_mid REAL,
    p_model REAL,
    p_mkt REAL,
    decision TEXT,
    reason_code TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    ts TEXT,
    mode TEXT,
    token_id TEXT,
    side TEXT,
    price REAL,
    size REAL,
    status TEXT
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT,
    ts TEXT,
    price REAL,
    size REAL
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
            await db.executescript(SCHEMA)
            await db.commit()

    async def execute(self, sql: str, params: tuple = ()) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(sql, params)
            await db.commit()
