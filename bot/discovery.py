from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp

from bot.config import Settings


logger = logging.getLogger(__name__)


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

    async with aiohttp.ClientSession() as session:
        scheduled_market = await _discover_scheduled_market(session, settings)
        if scheduled_market:
            return scheduled_market

        data = await _fetch_active_markets(session)

    now_iso = datetime.now(timezone.utc).isoformat()

    candidates = []
    for market in data:
        question = str(market.get("question", "")).lower()
        if "bitcoin" not in question or "up" not in question or "down" not in question:
            continue
        end_date = market.get("endDate") or market.get("end_date") or now_iso
        if end_date < now_iso:
            continue
        outcomes = _ensure_list(market.get("outcomes"))
        clob_ids = _ensure_list(market.get("clobTokenIds") or market.get("clob_token_ids"))
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

    logger.info(
        "Discovered market %s: UP=%s DOWN=%s via active-scan",
        str(market.get("slug", "unknown")),
        up_token_id,
        down_token_id,
    )

    return MarketDiscoveryResult(
        market_slug=str(market.get("slug", "unknown")),
        up_token_id=str(up_token_id),
        down_token_id=str(down_token_id),
    )


async def _discover_scheduled_market(session: aiohttp.ClientSession, settings: Settings) -> MarketDiscoveryResult | None:
    _ = settings
    window_seconds = 5 * 60
    now_ts = int(datetime.now(timezone.utc).timestamp())
    current_window_ts = (now_ts // window_seconds) * window_seconds

    candidate_timestamps = [
        current_window_ts,
        current_window_ts + window_seconds,
        current_window_ts - window_seconds,
        current_window_ts + (2 * window_seconds),
        current_window_ts - (2 * window_seconds),
    ]
    seen: set[int] = set()

    for unix_ts in candidate_timestamps:
        if unix_ts in seen or unix_ts <= 0:
            continue
        seen.add(unix_ts)

        slug = f"btc-updown-5m-{unix_ts}"
        event = await _fetch_event_by_slug(session, slug)
        if not event:
            continue

        result = _extract_market_tokens(event)
        if result:
            return result

    return None


async def _fetch_event_by_slug(session: aiohttp.ClientSession, slug: str) -> dict | None:
    url = f"https://gamma-api.polymarket.com/events/slug/{slug}"
    try:
        async with session.get(url, timeout=20) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            payload = await resp.json()
    except (aiohttp.ClientError, TimeoutError):
        return None

    if isinstance(payload, dict):
        return payload

    return None


def _extract_market_tokens(event: dict) -> MarketDiscoveryResult | None:
    markets = event.get("markets") or []
    for market in markets:
        outcomes = _ensure_list(market.get("outcomes"))
        clob_ids = _ensure_list(market.get("clobTokenIds") or market.get("clob_token_ids"))
        pairs = list(zip(outcomes, clob_ids))

        up_token_id = next((tid for name, tid in pairs if "up" in str(name).lower()), None)
        down_token_id = next((tid for name, tid in pairs if "down" in str(name).lower()), None)
        if up_token_id and down_token_id:
            market_slug = str(market.get("slug") or event.get("slug") or "unknown")
            logger.info("Discovered market %s: UP=%s DOWN=%s via event-slug", market_slug, up_token_id, down_token_id)
            return MarketDiscoveryResult(market_slug=market_slug, up_token_id=str(up_token_id), down_token_id=str(down_token_id))

    return None


async def _fetch_active_markets(session: aiohttp.ClientSession) -> list[dict]:
    url = "https://gamma-api.polymarket.com/markets"
    params = {"active": "true", "limit": "200"}

    async with session.get(url, params=params, timeout=20) as resp:
        resp.raise_for_status()
        payload = await resp.json()

    return payload if isinstance(payload, list) else []


def _ensure_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return []
        try:
            decoded = json.loads(candidate)
        except json.JSONDecodeError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []
