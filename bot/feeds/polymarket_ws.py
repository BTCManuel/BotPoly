from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import structlog
import websockets
from tenacity import retry, stop_after_attempt, wait_exponential

from bot.types import MarketQuote


class PolymarketMarketFeed:
    def __init__(self, ws_url: str, up_token_id: str, down_token_id: str, verbose: bool = False) -> None:
        self.ws_url = self._normalize_ws_url(ws_url)
        self.up_token_id = up_token_id
        self.down_token_id = down_token_id
        self.verbose = verbose
        self.up_quote: MarketQuote | None = None
        self.down_quote: MarketQuote | None = None
        self._version = 0
        self._log = structlog.get_logger("polymarket_ws")
        self._msg_counter_total = 0
        self._msg_type_counter: Counter[str] = Counter()
        self._last_stats_bucket: int | None = None
        self._last_msg_monotonic: float | None = None

    def switch_market(self, up_token_id: str, down_token_id: str) -> None:
        self.up_token_id = up_token_id
        self.down_token_id = down_token_id
        self.up_quote = None
        self.down_quote = None
        self._version += 1

    @property
    def msg_count_total(self) -> int:
        return self._msg_counter_total

    @property
    def last_msg_age_seconds(self) -> float | None:
        if self._last_msg_monotonic is None:
            return None
        return max(0.0, time.monotonic() - self._last_msg_monotonic)

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
                self._log.info("polymarket_connected", url=self.ws_url)
                for payload in self._subscription_payloads():
                    self._debug("polymarket_subscribe_payload", payload=payload)
                    await ws.send(json.dumps(payload))

                connected_at = time.monotonic()
                warned_no_messages_yet = False
                while True:
                    if version != self._version:
                        break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        if not warned_no_messages_yet and self._last_msg_monotonic is None and (time.monotonic() - connected_at) >= 10:
                            warned_no_messages_yet = True
                            self._log.warning("no_messages_received_yet")
                        continue

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
                "assets_ids": [self.up_token_id, self.down_token_id],
                "type": "market",
            },
            {
                "assets_ids": [self.up_token_id, self.down_token_id],
                "operation": "subscribe",
            },
        ]

    @staticmethod
    def _normalize_ws_url(ws_url: str) -> str:
        parsed = urlparse(ws_url)
        path = parsed.path or ""
        if path in ("", "/", "/ws"):
            path = "/ws/market"
        elif path == "/ws/":
            path = "/ws/market"
        return urlunparse(parsed._replace(path=path.rstrip("/") if path != "/ws/market" else path))

    def _on_message(self, msg: object) -> None:
        self._msg_counter_total += 1
        self._last_msg_monotonic = time.monotonic()

        msg_type = "unknown"
        if isinstance(msg, dict):
            msg_type = str(msg.get("type") or msg.get("event") or msg.get("channel") or "dict")
        elif isinstance(msg, list):
            msg_type = "list"
        self._msg_type_counter[msg_type] += 1

        if not self._debug_enabled():
            return

        bucket = int(datetime.now(timezone.utc).timestamp() // 60)
        if self._last_stats_bucket != bucket:
            self._last_stats_bucket = bucket
            msg_keys = list(msg.keys())[:10] if isinstance(msg, dict) else None
            self._debug(
                "polymarket_messages_received",
                total=self._msg_counter_total,
                msg_type=msg_type,
                keys=msg_keys,
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
        for key in ("data", "payload", "message", "event", "book", "books", "market", "result", "orders"):
            nested = msg.get(key)
            if isinstance(nested, dict) or isinstance(nested, list):
                out.extend(self._iter_quote_candidates(nested))
        return out

    def _extract_quote(self, msg: dict) -> MarketQuote | None:
        token_id = msg.get("asset_id") or msg.get("token_id") or msg.get("id")
        if token_id is None:
            self._debug("polymarket_quote_discarded", reason="missing_token_id", keys=list(msg.keys())[:10])
            return None

        bid = self._extract_book_price(msg, side="bid")
        ask = self._extract_book_price(msg, side="ask")
        if bid is None or ask is None:
            self._debug("polymarket_quote_discarded", token_id=str(token_id), reason="missing_bid_or_ask", bid=bid, ask=ask)
            return None

        quote = MarketQuote(token_id=str(token_id), bid=bid, ask=ask, ts=datetime.now(timezone.utc))
        if self._debug_enabled():
            self._debug("polymarket_quote_extracted", token_id=quote.token_id, bid=quote.bid, ask=quote.ask)
        return quote

    def _extract_book_price(self, msg: dict, side: str) -> float | None:
        best_key = "best_bid" if side == "bid" else "best_ask"
        fallback_key = "bid" if side == "bid" else "ask"
        direct = self._safe_float(msg.get(best_key) if msg.get(best_key) is not None else msg.get(fallback_key))
        if direct is not None:
            return direct

        levels_key = "bids" if side == "bid" else "asks"
        levels = msg.get(levels_key)
        level_price = self._extract_from_levels(levels)
        if level_price is not None:
            return level_price

        for nested_key in ("data", "book", "market", "payload", "message"):
            nested = msg.get(nested_key)
            if isinstance(nested, dict):
                nested_direct = self._extract_book_price(nested, side=side)
                if nested_direct is not None:
                    return nested_direct
        return None

    def _extract_from_levels(self, levels: object) -> float | None:
        if not isinstance(levels, list) or not levels:
            return None
        first = levels[0]
        if isinstance(first, dict):
            for key in ("price", "px", "p"):
                value = self._safe_float(first.get(key))
                if value is not None:
                    return value
            return None
        if isinstance(first, list) or isinstance(first, tuple):
            if not first:
                return None
            return self._safe_float(first[0])
        return None

    @staticmethod
    def _safe_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
