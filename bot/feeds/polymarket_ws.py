from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone

import structlog
import websockets
from tenacity import retry, stop_after_attempt, wait_exponential

from bot.types import MarketQuote


class PolymarketMarketFeed:
    def __init__(self, ws_url: str, up_token_id: str, down_token_id: str, verbose: bool = False) -> None:
        self.ws_url = ws_url
        self.up_token_id = up_token_id
        self.down_token_id = down_token_id
        self.verbose = verbose
        self.up_quote: MarketQuote | None = None
        self.down_quote: MarketQuote | None = None
        self._version = 0
        self._log = structlog.get_logger("polymarket_ws")
        self._msg_counter = 0
        self._msg_type_counter: Counter[str] = Counter()
        self._last_stats_bucket: int | None = None

    def switch_market(self, up_token_id: str, down_token_id: str) -> None:
        self.up_token_id = up_token_id
        self.down_token_id = down_token_id
        self.up_quote = None
        self.down_quote = None
        self._version += 1

    def _debug_enabled(self) -> bool:
        return self.verbose or logging.getLogger().isEnabledFor(logging.DEBUG)

    def _debug(self, event: str, **kwargs: object) -> None:
        if self.verbose:
            self._log.info(event, **kwargs)
        elif self._debug_enabled():
            self._log.debug(event, **kwargs)

    @retry(wait=wait_exponential(multiplier=1, min=1, max=30), stop=stop_after_attempt(999999))
    async def run(self) -> None:
        while True:
            version = self._version
            async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
                for payload in self._subscription_payloads():
                    self._debug("polymarket_subscribe_payload", payload=payload)
                    await ws.send(json.dumps(payload))

                async for raw in ws:
                    if version != self._version:
                        break
                    msg = json.loads(raw)
                    self._on_message(msg)
                    for quote in self._extract_quotes(msg):
                        if quote.token_id == self.up_token_id:
                            self.up_quote = quote
                        elif quote.token_id == self.down_token_id:
                            self.down_quote = quote

    def _subscription_payloads(self) -> list[dict]:
        return [
            {
                "type": "market",
                "asset_ids": [self.up_token_id, self.down_token_id],
            },
            {
                "type": "subscribe",
                "channel": "market",
                "asset_ids": [self.up_token_id, self.down_token_id],
            },
        ]

    def _on_message(self, msg: object) -> None:
        if not self._debug_enabled():
            return
        self._msg_counter += 1
        msg_type = "unknown"
        if isinstance(msg, dict):
            msg_type = str(msg.get("type") or msg.get("event") or msg.get("channel") or "dict")
        elif isinstance(msg, list):
            msg_type = "list"
        self._msg_type_counter[msg_type] += 1

        bucket = int(datetime.now(timezone.utc).timestamp() // 60)
        if self._last_stats_bucket != bucket:
            self._last_stats_bucket = bucket
            self._debug(
                "polymarket_messages_received",
                total=self._msg_counter,
                types=dict(self._msg_type_counter),
            )

    def _extract_quotes(self, msg: object) -> list[MarketQuote]:
        out: list[MarketQuote] = []
        for candidate in self._iter_quote_candidates(msg):
            quote = self._extract_quote(candidate)
            if quote is not None:
                out.append(quote)
        return out

    def _iter_quote_candidates(self, msg: object) -> list[dict]:
        if isinstance(msg, list):
            out: list[dict] = []
            for item in msg:
                out.extend(self._iter_quote_candidates(item))
            return out

        if not isinstance(msg, dict):
            return []

        out = [msg]
        for key in ("data", "payload", "message", "event", "book", "books"):
            nested = msg.get(key)
            if isinstance(nested, dict) or isinstance(nested, list):
                out.extend(self._iter_quote_candidates(nested))
        return out

    def _extract_quote(self, msg: dict) -> MarketQuote | None:
        token_id = msg.get("asset_id") or msg.get("token_id")
        if token_id is None:
            return None

        bid = self._safe_float(msg.get("best_bid") if msg.get("best_bid") is not None else msg.get("bid"))
        ask = self._safe_float(msg.get("best_ask") if msg.get("best_ask") is not None else msg.get("ask"))
        if bid is None or ask is None:
            self._debug("polymarket_quote_discarded", token_id=str(token_id), bid=msg.get("best_bid") or msg.get("bid"), ask=msg.get("best_ask") or msg.get("ask"))
            return None

        quote = MarketQuote(token_id=str(token_id), bid=bid, ask=ask, ts=datetime.now(timezone.utc))
        self._debug("polymarket_quote_extracted", token_id=quote.token_id, bid=quote.bid, ask=quote.ask)
        return quote

    @staticmethod
    def _safe_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
