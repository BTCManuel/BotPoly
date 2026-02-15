from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog

from bot.config import Settings
from bot.discovery import MarketDiscoveryResult, discover_btc_up_down_market
from bot.execution import Executor
from bot.feeds.binance import BinanceFeed
from bot.feeds.polymarket_ws import PolymarketMarketFeed
from bot.model import MomentumVolModel
from bot.risk import RiskManager
from bot.storage import Storage
from bot.strategy import choose_signal
from bot.types import Decision, Position


@dataclass(slots=True)
class Stats:
    reason_counts: Counter
    edge_up: list[float]
    edge_down: list[float]
    spread_up: list[float]
    spread_down: list[float]


def _fmt(v: float) -> str:
    return f"{v:.4f}"


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

    active_market = discovered
    last_valid_market = discovered
    last_market_ok = datetime.now(timezone.utc)

    position: Position | None = None
    stats = Stats(reason_counts=Counter(), edge_up=[], edge_down=[], spread_up=[], spread_down=[])

    async def rotation_loop() -> None:
        nonlocal active_market, last_valid_market, last_market_ok
        while True:
            await asyncio.sleep(settings.rotate_interval_seconds)
            prev = active_market
            new_market = await discover_btc_up_down_market(settings)
            now = datetime.now(timezone.utc)
            if new_market:
                last_valid_market = new_market
                last_market_ok = now
                if new_market.market_slug != prev.market_slug:
                    active_market = new_market
                    poly.switch_market(new_market.up_token_id, new_market.down_token_id)
                    log.info(
                        "market_rotated",
                        old_slug=prev.market_slug,
                        new_slug=new_market.market_slug,
                        old_up=prev.up_token_id,
                        old_down=prev.down_token_id,
                        new_up=new_market.up_token_id,
                        new_down=new_market.down_token_id,
                    )
            else:
                age = (now - last_market_ok).total_seconds()
                if age <= settings.market_discovery_fallback_seconds:
                    active_market = last_valid_market
                    log.warning("market_discovery_failed_using_fallback", fallback_slug=last_valid_market.market_slug, age_seconds=age)
                else:
                    log.error("market_discovery_failed_expired_fallback", age_seconds=age)

    async def decision_loop() -> None:
        nonlocal position
        while True:
            await asyncio.sleep(settings.loop_interval_seconds)
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

            stats.edge_up.append(signal.edge_up)
            stats.edge_down.append(signal.edge_down)
            stats.spread_up.append(poly.up_quote.spread)
            stats.spread_down.append(poly.down_quote.spread)
            reason = signal.reason_code

            if signal.decision != Decision.HOLD and position and not settings.allow_cross_window_positions:
                reason = "position_open_old_window"
                signal = choose_signal(p_model, poly.up_quote.mid, 9999, settings.max_spread, poly.up_quote.spread, poly.down_quote.spread)

            can_open, risk_reason = risk.can_open(settings.order_size_usd)
            if signal.decision != Decision.HOLD and not can_open:
                reason = risk_reason

            stats.reason_counts[reason] += 1

            await storage.execute(
                "INSERT INTO ticks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    active_market.market_slug,
                    active_market.up_token_id,
                    active_market.down_token_id,
                    binance.latest_price,
                    poly.up_quote.bid,
                    poly.up_quote.ask,
                    poly.up_quote.mid,
                    poly.down_quote.bid,
                    poly.down_quote.ask,
                    poly.down_quote.mid,
                    signal.p_up_model,
                    signal.p_up_mkt,
                    signal.p_down_mkt,
                    signal.edge_up,
                    signal.edge_down,
                    signal.decision.value,
                    reason,
                ),
            )

            if settings.verbose:
                print(
                    f"{datetime.now(timezone.utc).isoformat()} slug={active_market.market_slug} "
                    f"UP={active_market.up_token_id} DOWN={active_market.down_token_id} "
                    f"btc={_fmt(binance.latest_price)} up(b/a/m)={_fmt(poly.up_quote.bid)}/{_fmt(poly.up_quote.ask)}/{_fmt(poly.up_quote.mid)} "
                    f"dn(b/a/m)={_fmt(poly.down_quote.bid)}/{_fmt(poly.down_quote.ask)}/{_fmt(poly.down_quote.mid)} "
                    f"p_model={_fmt(signal.p_up_model)} p_mkt={_fmt(signal.p_up_mkt)} edge_up={_fmt(signal.edge_up)} edge_dn={_fmt(signal.edge_down)} "
                    f"spr_up={_fmt(poly.up_quote.spread)} spr_dn={_fmt(poly.down_quote.spread)} dec={signal.decision.value} reason={reason}"
                )

            if position:
                quote = poly.up_quote if position.token_id == active_market.up_token_id else poly.down_quote
                elapsed = (datetime.now(timezone.utc) - position.entry_ts).total_seconds()
                target = position.entry_price * (1 + settings.profit_take_bps / 10000)
                exit_reason = None
                if quote.mid >= target:
                    exit_reason = "profit_take"
                elif elapsed >= settings.time_stop_seconds:
                    exit_reason = "time_stop"
                if exit_reason:
                    sell = await executor.place_limit(position.token_id, "sell", quote.bid, position.qty, best_bid=quote.bid)
                    await storage.execute(
                        "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            sell.order_id,
                            position.market_slug,
                            settings.mode.value,
                            position.token_id,
                            "sell",
                            sell.price,
                            sell.size,
                            sell.status,
                            exit_reason,
                            executor.now_iso(),
                            executor.now_iso(),
                        ),
                    )
                    if sell.status == "filled":
                        await storage.execute("INSERT INTO fills (order_id, ts, fill_price, fill_size) VALUES (?,?,?,?)", (sell.order_id, executor.now_iso(), sell.price, sell.size))
                    pnl = (sell.price - position.entry_price) * position.qty
                    risk.on_close(position.entry_price * position.qty, pnl)
                    await storage.execute("UPDATE positions SET closed_ts = ?, exit_reason = ? WHERE id = (SELECT id FROM positions WHERE token_id = ? AND closed_ts IS NULL ORDER BY opened_ts DESC LIMIT 1)", (executor.now_iso(), exit_reason, position.token_id))
                    await storage.execute("INSERT INTO pnl VALUES (?,?,?,?)", (executor.now_iso(), risk.state.realized_pnl_usd, 0.0, risk.state.exposure_usd))
                    if settings.verbose:
                        print(f"EXIT {exit_reason} token={position.token_id} price={sell.price:.4f} pnl={pnl:.4f} status={sell.status}")
                    position = None
                continue

            if signal.decision == Decision.HOLD or not can_open:
                if signal.decision != Decision.HOLD and not can_open:
                    await storage.execute("INSERT INTO errors VALUES (?,?,?)", (executor.now_iso(), "risk", risk_reason))
                continue

            buy_token_id = active_market.up_token_id if signal.decision == Decision.BUY_UP else active_market.down_token_id
            quote = poly.up_quote if signal.decision == Decision.BUY_UP else poly.down_quote
            limit_price = quote.ask
            qty = settings.order_size_usd / max(limit_price, 0.01)

            result = await executor.place_limit(buy_token_id, "buy", limit_price, qty, best_ask=quote.ask)
            await storage.execute(
                "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    result.order_id,
                    active_market.market_slug,
                    settings.mode.value,
                    buy_token_id,
                    "buy",
                    result.price,
                    result.size,
                    result.status,
                    signal.reason_code,
                    executor.now_iso(),
                    executor.now_iso(),
                ),
            )
            if result.status == "filled":
                await storage.execute("INSERT INTO fills (order_id, ts, fill_price, fill_size) VALUES (?,?,?,?)", (result.order_id, executor.now_iso(), result.price, result.size))
                risk.on_open(settings.order_size_usd)
                position = Position(
                    market_slug=active_market.market_slug,
                    token_id=buy_token_id,
                    qty=qty,
                    entry_price=limit_price,
                    entry_ts=datetime.now(timezone.utc),
                    order_id=result.order_id,
                )
                await storage.execute(
                    "INSERT INTO positions (market_slug, token_id, entry_price, size, opened_ts, closed_ts, exit_reason) VALUES (?,?,?,?,?,?,?)",
                    (active_market.market_slug, buy_token_id, limit_price, qty, executor.now_iso(), None, None),
                )
            if settings.verbose:
                print(
                    f"ORDER {signal.decision.value} token={buy_token_id} limit={limit_price:.4f} size={qty:.4f} fill_if={'price>=ask'} status={result.status}"
                )

            log.info("decision", decision=signal.decision.value, edge=signal.edge, reason=reason)

    tasks = [
        asyncio.create_task(binance.run()),
        asyncio.create_task(poly.run()),
        asyncio.create_task(rotation_loop()),
        asyncio.create_task(decision_loop()),
    ]
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

        with_trades = stats.reason_counts.get("edge_up", 0) + stats.reason_counts.get("edge_down", 0)
        if with_trades == 0:
            def summary(vals: list[float]) -> tuple[float, float, float]:
                if not vals:
                    return (0.0, 0.0, 0.0)
                return (min(vals), max(vals), sum(vals) / len(vals))

            eup = summary(stats.edge_up)
            edn = summary(stats.edge_down)
            sup = summary(stats.spread_up)
            sdn = summary(stats.spread_down)
            log.info(
                "no_trades_summary",
                reason_breakdown=dict(stats.reason_counts),
                edge_up={"min": eup[0], "max": eup[1], "avg": eup[2]},
                edge_down={"min": edn[0], "max": edn[1], "avg": edn[2]},
                spread_up={"min": sup[0], "max": sup[1], "avg": sup[2]},
                spread_down={"min": sdn[0], "max": sdn[1], "avg": sdn[2]},
            )
