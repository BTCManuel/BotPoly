from __future__ import annotations

import argparse
import asyncio

from bot.config import get_settings
from bot.logging_utils import configure_logging
from bot.report import build_session_report
from bot.runner import run_bot
from bot.types import Mode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket BTC Up/Down bot")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run trading bot")
    run.add_argument("--mode", choices=["paper", "live"], default=None, help="Override MODE from env")
    run.add_argument("--hours", type=float, default=None, help="Auto-stop after N hours (e.g. 1 or 24)")

    report = sub.add_parser("report", help="Print simple PnL/order summary from SQLite")
    report.add_argument("--mode", choices=["paper", "live"], default=None, help="Mode filter for orders")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    if args.mode:
        settings.mode = Mode(args.mode)

    configure_logging(settings.log_level)
    if args.command == "run":
        max_runtime_seconds = int(args.hours * 3600) if args.hours and args.hours > 0 else None
        asyncio.run(run_bot(settings, max_runtime_seconds=max_runtime_seconds))
    elif args.command == "report":
        report = build_session_report(settings.sqlite_path, settings.mode.value)
        print(f"mode={settings.mode.value}")
        print(f"orders_total={report.total_orders}")
        print(f"orders_buy={report.buy_orders}")
        print(f"orders_sell={report.sell_orders}")
        print(f"open_buy_positions={report.open_buys}")
        print(f"realized_pnl_usd={report.realized_pnl_usd:.4f}")


if __name__ == "__main__":
    main()
