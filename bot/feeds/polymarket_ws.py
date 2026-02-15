from __future__ import annotations

import json
from datetime import datetime, timezone

import websockets
from tenacity import retry, stop_after_attempt, wait_exponential

from bot.types import MarketQuote


class PolymarketMarketFeed:
    def __init__(self, ws_url: str, up_token_id: str, down_token_id: str) -> None:
        self.ws_url = ws_url
        self.up_token_id = up_token_id
        self.down_token_id = down_token_id
        self.up_quote: MarketQuote | None = None
        self.down_quote: MarketQuote | None = None
        self._version = 0

    def switch_market(self, up_token_id: str, down_token_id: str) -> None:
        self.up_token_id = up_token_id
        self.down_token_id = down_token_id
        self.up_quote = None
        self.down_quote = None
        self._version += 1

    @retry(wait=wait_exponential(multiplier=1, min=1, max=30), stop=stop_after_attempt(999999))
    async def run(self) -> None:
        while True:
            version = self._version
            async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
                sub_msg = {
                    "type": "market",
                    "assets_ids": [self.up_token_id, self.down_token_id],
                }
                await ws.send(json.dumps(sub_msg))
                async for raw in ws:
                    if version != self._version:
                        break
                    msg = json.loads(raw)
                    quote = self._extract_quote(msg)
                    if not quote:
                        continue
                    if quote.token_id == self.up_token_id:
                        self.up_quote = quote
                    elif quote.token_id == self.down_token_id:
                        self.down_quote = quote

    def _extract_quote(self, msg: dict) -> MarketQuote | None:
        token_id = msg.get("asset_id") or msg.get("token_id")
        bid = msg.get("best_bid") or msg.get("bid")
        ask = msg.get("best_ask") or msg.get("ask")
        if token_id is None or bid is None or ask is None:
            return None
        return MarketQuote(token_id=str(token_id), bid=float(bid), ask=float(ask), ts=datetime.now(timezone.utc))
