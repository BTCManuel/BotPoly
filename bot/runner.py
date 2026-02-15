from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from bot.config import Settings
from bot.discovery import discover_btc_up_down_market
from bot.execution import Executor
from bot.feeds.binance import BinanceFeed
from bot.feeds.polymarket_ws import PolymarketMarketFeed
from bot.model import MomentumVolModel
from bot.risk import RiskManager
from bot.storage import Storage
from bot.strategy import choose_signal
from bot.types import Decision, Position


async def run_bot(settings: Settings, max_runtime_seconds: int | None = None) -> None:
    log = structlog.get_logger("bot")
    storage = Storage(settings.sqlite_path)
    await storage.init()

    discovered = await discover_btc_up_down_market(settings)
    if not discovered:
        raise RuntimeError("Market discovery failed and no fallback token IDs provided")

    log.info("market_selected", slug=discovered.market_slug, up_token=discovered.up_token_id, down_token=discovered.down_token_id)

    binance = BinanceFeed(settings.binance_ws_url)
    poly = PolymarketMarketFeed(settings.poly_ws_url, discovered.up_token_id, discovered.down_token_id)
    model = MomentumVolModel(settings.momentum_window, settings.vol_window)
    risk = RiskManager(settings.max_position_usd, settings.daily_loss_limit_usd, settings.cooldown_seconds)
    executor = Executor(settings)

    position: Position | None = None

    async def decision_loop() -> None:
        nonlocal position
        while True:
            await asyncio.sleep(1)
            if not binance.latest_price or not poly.up_quote or not poly.down_quote:
                continue

            p_model = model.predict_up_probability(binance.prices)
            signal = choose_signal(
                p_up_model=p_model,
                up_mid=poly.up_quote.mid,
                edge_min=settings.edge_min,
                max_spread=settings.max_spread,
                up_spread=poly.up_quote.spread,
                down_spread=poly.down_quote.spread,
            )

            await storage.execute(
                "INSERT INTO ticks VALUES (?,?,?,?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    binance.latest_price,
                    poly.up_quote.mid,
                    poly.down_quote.mid,
                    signal.p_up_model,
                    signal.p_up_mkt,
                    signal.decision.value,
                    signal.reason_code,
                ),
            )

            if position:
                quote = poly.up_quote if position.token_id == discovered.up_token_id else poly.down_quote
                elapsed = (datetime.now(timezone.utc) - position.entry_ts).total_seconds()
                target = position.entry_price * (1 + settings.profit_take_bps / 10000)
                if quote.mid >= target or elapsed >= settings.time_stop_seconds:
                    sell = await executor.place_limit(position.token_id, "sell", quote.bid, position.qty)
                    pnl = (sell.price - position.entry_price) * position.qty
                    risk.on_close(position.entry_price * position.qty, pnl)
                    await storage.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)", (sell.order_id, executor.now_iso(), settings.mode.value, position.token_id, "sell", sell.price, sell.size, sell.status))
                    await storage.execute("INSERT INTO pnl VALUES (?,?,?,?)", (executor.now_iso(), risk.state.realized_pnl_usd, 0.0, risk.state.exposure_usd))
                    position = None
                continue

            if signal.decision == Decision.HOLD:
                continue

            can_open, reason = risk.can_open(settings.order_size_usd)
            if not can_open:
                await storage.execute("INSERT INTO errors VALUES (?,?,?)", (executor.now_iso(), "risk", reason))
                continue

            buy_token_id = discovered.up_token_id if signal.decision == Decision.BUY_UP else discovered.down_token_id
            quote = poly.up_quote if signal.decision == Decision.BUY_UP else poly.down_quote
            limit_price = quote.ask
            qty = settings.order_size_usd / max(limit_price, 0.01)

            result = await executor.place_limit(buy_token_id, "buy", limit_price, qty, best_ask=quote.ask)
            await storage.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)", (result.order_id, executor.now_iso(), settings.mode.value, buy_token_id, "buy", result.price, result.size, result.status))

            if result.status in {"filled", "submitted", "open"}:
                risk.on_open(settings.order_size_usd)
                position = Position(token_id=buy_token_id, qty=qty, entry_price=limit_price, entry_ts=datetime.now(timezone.utc), order_id=result.order_id)

            log.info("decision", decision=signal.decision.value, edge=signal.edge, reason=signal.reason_code)

    tasks = [asyncio.create_task(binance.run()), asyncio.create_task(poly.run()), asyncio.create_task(decision_loop())]
    try:
        if max_runtime_seconds and max_runtime_seconds > 0:
            await asyncio.sleep(max_runtime_seconds)
            log.info("max_runtime_reached", seconds=max_runtime_seconds)
        else:
            await asyncio.gather(*tasks)
            return
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
