from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import math

import structlog

from bot.config import Settings
from bot.discovery import discover_btc_up_down_market
from bot.execution import Executor
from bot.feeds.binance import BinanceFeed
from bot.feeds.polymarket_ws import PolymarketMarketFeed
from bot.model import MomentumVolModel
from bot.risk import RiskManager
from bot.report import build_session_report
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
    poly = PolymarketMarketFeed(
        settings.poly_ws_url,
        discovered.up_token_id,
        discovered.down_token_id,
        verbose=settings.verbose,
    )
    model = MomentumVolModel(settings.momentum_window, settings.vol_window)
    risk = RiskManager(settings.max_position_usd, settings.daily_loss_limit_usd, settings.cooldown_seconds)
    executor = Executor(settings)

    active_market = discovered
    last_valid_market = discovered
    last_market_ok = datetime.now(timezone.utc)

    position: Position | None = None
    stats = Stats(reason_counts=Counter(), edge_up=[], edge_down=[], spread_up=[], spread_down=[])
    quote_interval = max(settings.quote_print_interval_seconds, 1)
    last_quote_bucket: int | None = None

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
                token_changed = (new_market.up_token_id != prev.up_token_id) or (new_market.down_token_id != prev.down_token_id)
                if new_market.market_slug != prev.market_slug or token_changed:
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
        nonlocal position, last_quote_bucket
        while True:
            await asyncio.sleep(settings.loop_interval_seconds)
            ts = datetime.now(timezone.utc).timestamp()
            btc_price = binance.latest_price

            up_quote = poly.up_quote
            down_quote = poly.down_quote
            quote_bucket = math.floor(ts / quote_interval)
            should_print_quotes = quote_bucket != last_quote_bucket
            if should_print_quotes:
                last_quote_bucket = quote_bucket

            if not btc_price or not up_quote or not down_quote:
                reason = "no_orderbook"
                stats.reason_counts[reason] += 1
                await storage.execute(
                    "INSERT INTO ticks (ts, btc_price, up_mid, down_mid, p_model, decision, edge, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (ts, btc_price or 0.0, 0.0, 0.0, 0.0, Decision.HOLD.value, 0.0, reason),
                )
                if settings.verbose or should_print_quotes:
                    print(
                        f"[{datetime.now(timezone.utc).isoformat()}] BTC={_fmt(btc_price or 0.0)} "
                        "UP(mid=0.0000, spread=0.0000) DOWN(mid=0.0000, spread=0.0000) "
                        "p_model=0.0000 edge_up=0.0000 edge_down=0.0000 decision=hold reason=no_orderbook"
                    )
                continue

            if up_quote.bid is None or up_quote.ask is None or down_quote.bid is None or down_quote.ask is None:
                reason = "no_orderbook"
                stats.reason_counts[reason] += 1
                await storage.execute(
                    "INSERT INTO ticks (ts, btc_price, up_mid, down_mid, p_model, decision, edge, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (ts, btc_price, 0.0, 0.0, 0.0, Decision.HOLD.value, 0.0, reason),
                )
                if settings.verbose or should_print_quotes:
                    print(
                        f"[{datetime.now(timezone.utc).isoformat()}] BTC={_fmt(btc_price)} "
                        "UP(mid=0.0000, spread=0.0000) DOWN(mid=0.0000, spread=0.0000) "
                        "p_model=0.0000 edge_up=0.0000 edge_down=0.0000 decision=hold reason=no_orderbook"
                    )
                continue

            p_model = model.predict_up_probability(binance.prices)
            signal = choose_signal(
                p_up_model=p_model,
                up_mid=up_quote.mid,
                edge_min=settings.edge_min,
                max_spread=settings.max_spread,
                up_spread=up_quote.spread,
                down_spread=down_quote.spread,
            )

            stats.edge_up.append(signal.edge_up)
            stats.edge_down.append(signal.edge_down)
            stats.spread_up.append(up_quote.spread)
            stats.spread_down.append(down_quote.spread)
            reason = signal.reason_code

            if signal.decision != Decision.HOLD and position and not settings.allow_cross_window_positions:
                reason = "position_open_old_window"
                signal = choose_signal(p_model, up_quote.mid, 9999, settings.max_spread, up_quote.spread, down_quote.spread)

            can_open, risk_reason = risk.can_open(settings.order_size_usd)
            if signal.decision != Decision.HOLD and not can_open:
                reason = risk_reason

            stats.reason_counts[reason] += 1

            if settings.verbose or should_print_quotes:
                print(
                    f"[{datetime.now(timezone.utc).isoformat()}] BTC={_fmt(btc_price)} "
                    f"UP(mid={_fmt(up_quote.mid)}, spread={_fmt(up_quote.spread)}) "
                    f"DOWN(mid={_fmt(down_quote.mid)}, spread={_fmt(down_quote.spread)}) "
                    f"p_model={_fmt(signal.p_up_model)} edge_up={_fmt(signal.edge_up)} edge_down={_fmt(signal.edge_down)} "
                    f"decision={signal.decision.value} reason={reason}"
                )

            await storage.execute(
                "INSERT INTO ticks (ts, btc_price, up_mid, down_mid, p_model, decision, edge, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, btc_price, up_quote.mid, down_quote.mid, signal.p_up_model, signal.decision.value, signal.edge, reason),
            )

            if position:
                if position.token_id == active_market.up_token_id:
                    quote = up_quote
                elif position.token_id == active_market.down_token_id:
                    quote = down_quote
                else:
                    continue

                elapsed = (datetime.now(timezone.utc) - position.entry_ts).total_seconds()
                target = position.entry_price * (1 + settings.profit_take_bps / 10000)
                exit_reason = None
                if quote.mid >= target:
                    exit_reason = "profit_take"
                elif elapsed >= settings.time_stop_seconds:
                    exit_reason = "time_stop"
                if exit_reason:
                    sell = await executor.place_limit(position.token_id, "sell", quote.bid, position.qty, best_bid=quote.bid)
                    now_ts = datetime.now(timezone.utc).timestamp()
                    await storage.execute(
                        "INSERT INTO orders (id, market_slug, token_id, side, price, size, status, reason, created_ts, updated_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            sell.order_id,
                            position.market_slug,
                            position.token_id,
                            "sell",
                            sell.price,
                            sell.size,
                            sell.status,
                            exit_reason,
                            now_ts,
                            now_ts,
                        ),
                    )
                    if sell.status == "filled":
                        await storage.execute(
                            "INSERT INTO fills (order_id, fill_price, fill_size, ts) VALUES (?, ?, ?, ?)",
                            (sell.order_id, sell.price, sell.size, now_ts),
                        )
                        pnl = (sell.price - position.entry_price) * position.qty
                        risk.on_close(position.entry_price * position.qty, pnl)
                        await storage.execute(
                            "UPDATE positions SET closed_ts = ?, exit_reason = ? WHERE id = (SELECT id FROM positions WHERE token_id = ? AND closed_ts IS NULL ORDER BY opened_ts DESC LIMIT 1)",
                            (now_ts, exit_reason, position.token_id),
                        )
                        await storage.execute(
                            "INSERT INTO pnl (ts, realized, unrealized) VALUES (?, ?, ?)",
                            (now_ts, risk.state.realized_pnl_usd, 0.0),
                        )
                        if settings.verbose:
                            print(
                                f"TRADE EXECUTED: side=sell price={sell.price:.4f} size={sell.size:.4f} status={sell.status}"
                            )
                        position = None
                continue

            if signal.decision == Decision.HOLD or not can_open:
                if signal.decision != Decision.HOLD and not can_open:
                    await storage.execute(
                        "INSERT INTO errors (ts, source, message) VALUES (?, ?, ?)",
                        (datetime.now(timezone.utc).timestamp(), "risk", risk_reason),
                    )
                continue

            buy_token_id = active_market.up_token_id if signal.decision == Decision.BUY_UP else active_market.down_token_id
            quote = up_quote if signal.decision == Decision.BUY_UP else down_quote
            limit_price = quote.ask
            qty = settings.order_size_usd / max(limit_price, 0.01)

            result = await executor.place_limit(buy_token_id, "buy", limit_price, qty, best_ask=quote.ask)
            now_ts = datetime.now(timezone.utc).timestamp()
            await storage.execute(
                "INSERT INTO orders (id, market_slug, token_id, side, price, size, status, reason, created_ts, updated_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.order_id,
                    active_market.market_slug,
                    buy_token_id,
                    "buy",
                    result.price,
                    result.size,
                    result.status,
                    reason,
                    now_ts,
                    now_ts,
                ),
            )
            if result.status == "filled":
                await storage.execute(
                    "INSERT INTO fills (order_id, fill_price, fill_size, ts) VALUES (?, ?, ?, ?)",
                    (result.order_id, result.price, result.size, now_ts),
                )
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
                    "INSERT INTO positions (token_id, entry_price, size, opened_ts, closed_ts, exit_reason) VALUES (?, ?, ?, ?, ?, ?)",
                    (buy_token_id, limit_price, qty, now_ts, None, None),
                )
            if settings.verbose:
                print(f"TRADE EXECUTED: side=buy price={result.price:.4f} size={result.size:.4f} status={result.status}")

            log.info("decision", decision=signal.decision.value, edge=signal.edge, reason=reason)

    def _track_task(name: str, task: asyncio.Task[None]) -> None:
        if settings.verbose or settings.log_level.upper() == "DEBUG":
            log.info(f"{name}_started")

        def _on_done(done: asyncio.Task[None]) -> None:
            if done.cancelled():
                return
            exc = done.exception()
            if exc is not None:
                log.error(f"{name}_crashed", error=str(exc))

        task.add_done_callback(_on_done)

    binance_task = asyncio.create_task(binance.run(), name="binance_feed")
    poly_task = asyncio.create_task(poly.run(), name="polymarket_feed")
    rotation_task = asyncio.create_task(rotation_loop(), name="rotation_loop")
    decision_task = asyncio.create_task(decision_loop(), name="decision_loop")

    _track_task("binance_feed", binance_task)
    _track_task("polymarket_feed", poly_task)
    _track_task("rotation_loop", rotation_task)
    _track_task("decision_loop", decision_task)

    tasks = [binance_task, poly_task, rotation_task, decision_task]
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

        report = build_session_report(settings.sqlite_path, settings.mode.value)
        print("\n=== Ergebnis ===")
        print(f"mode={settings.mode.value}")
        print(f"orders_total={report.total_orders}")
        print(f"orders_buy={report.buy_orders}")
        print(f"orders_sell={report.sell_orders}")
        print(f"fills_total={report.fills_total}")
        print(f"positions_open={report.open_positions}")
        print(f"positions_closed={report.closed_positions}")
        print(f"realized_pnl_usd={report.realized_pnl_usd:.4f}")
