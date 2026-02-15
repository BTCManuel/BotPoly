from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp

from bot.config import Settings


@dataclass(slots=True)
class MarketDiscoveryResult:
    market_slug: str
    up_token_id: str
    down_token_id: str


async def discover_btc_up_down_market(settings: Settings) -> MarketDiscoveryResult | None:
    if settings.up_token_id and settings.down_token_id:
        return MarketDiscoveryResult(
            market_slug="manual-config",
            up_token_id=settings.up_token_id,
            down_token_id=settings.down_token_id,
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    url = "https://gamma-api.polymarket.com/markets"
    params = {"active": "true", "limit": "200"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=20) as resp:
            resp.raise_for_status()
            data = await resp.json()

    candidates = []
    for market in data:
        question = str(market.get("question", "")).lower()
        if "bitcoin" not in question or "up" not in question or "down" not in question:
            continue
        end_date = market.get("endDate") or market.get("end_date") or now_iso
        if end_date < now_iso:
            continue
        outcomes = market.get("outcomes") or []
        clob_ids = market.get("clobTokenIds") or market.get("clob_token_ids") or []
        if len(outcomes) >= 2 and len(clob_ids) >= 2:
            candidates.append((market, outcomes, clob_ids))

    if not candidates:
        return None

    market, outcomes, clob_ids = candidates[0]
    pairs = list(zip(outcomes, clob_ids))
    up_token_id = next((tid for name, tid in pairs if "up" in str(name).lower()), None)
    down_token_id = next((tid for name, tid in pairs if "down" in str(name).lower()), None)
    if not up_token_id or not down_token_id:
        return None

    return MarketDiscoveryResult(
        market_slug=str(market.get("slug", "unknown")),
        up_token_id=str(up_token_id),
        down_token_id=str(down_token_id),
    )
