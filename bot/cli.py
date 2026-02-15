from __future__ import annotations

import argparse
import asyncio

from bot.config import get_settings
from bot.logging_utils import configure_logging
from bot.runner import run_bot
from bot.types import Mode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket BTC Up/Down bot")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run trading bot")
    run.add_argument("--mode", choices=["paper", "live"], default=None, help="Override MODE from env")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    if args.mode:
        settings.mode = Mode(args.mode)

    configure_logging(settings.log_level)
    if args.command == "run":
        asyncio.run(run_bot(settings))


if __name__ == "__main__":
    main()
