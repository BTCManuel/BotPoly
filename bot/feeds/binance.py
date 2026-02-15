from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone

import websockets
from tenacity import retry, stop_after_attempt, wait_exponential


class BinanceFeed:
    def __init__(self, ws_url: str, maxlen: int = 5000) -> None:
        self.ws_url = ws_url
        self.prices: deque[float] = deque(maxlen=maxlen)
        self.timestamps: deque[datetime] = deque(maxlen=maxlen)
        self._latest_price: float | None = None

    @property
    def latest_price(self) -> float | None:
        return self._latest_price

    @retry(wait=wait_exponential(multiplier=1, min=1, max=30), stop=stop_after_attempt(999999))
    async def run(self) -> None:
        async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
            async for raw in ws:
                msg = json.loads(raw)
                price = float(msg["p"])
                self._latest_price = price
                self.prices.append(price)
                self.timestamps.append(datetime.now(timezone.utc))
                await asyncio.sleep(0)
