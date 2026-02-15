from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

from bot.types import Mode


@dataclass(slots=True)
class Settings:
    mode: Mode
    log_level: str
    sqlite_path: str
    poly_clob_host: str
    poly_ws_url: str
    poly_chain_id: int
    poly_private_key: str | None
    poly_api_key: str | None
    poly_api_secret: str | None
    poly_api_passphrase: str | None
    up_token_id: str | None
    down_token_id: str | None
    binance_ws_url: str
    edge_min: float
    max_spread: float
    order_size_usd: float
    max_position_usd: float
    daily_loss_limit_usd: float
    cooldown_seconds: int
    profit_take_bps: int
    time_stop_seconds: int
    vol_window: int
    momentum_window: int
    market_search: str
    window_minutes: int
    loop_interval_seconds: float
    rotate_interval_seconds: int
    quote_print_interval_seconds: int
    paper_fill_epsilon: float
    allow_cross_window_positions: bool
    market_discovery_fallback_seconds: int
    verbose: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    mode = Mode(os.getenv("MODE", "paper").lower())
    return Settings(
        mode=mode,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        sqlite_path=os.getenv("SQLITE_PATH", "bot.db"),
        poly_clob_host=os.getenv("POLY_CLOB_HOST", "https://clob.polymarket.com"),
        poly_ws_url=os.getenv("POLY_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/"),
        poly_chain_id=int(os.getenv("POLY_CHAIN_ID", "137")),
        poly_private_key=os.getenv("POLY_PRIVATE_KEY"),
        poly_api_key=os.getenv("POLY_API_KEY"),
        poly_api_secret=os.getenv("POLY_API_SECRET"),
        poly_api_passphrase=os.getenv("POLY_API_PASSPHRASE"),
        up_token_id=os.getenv("UP_TOKEN_ID"),
        down_token_id=os.getenv("DOWN_TOKEN_ID"),
        binance_ws_url=os.getenv("BINANCE_WS_URL", "wss://stream.binance.com:9443/ws/btcusdt@trade"),
        edge_min=float(os.getenv("EDGE_MIN", "0.04")),
        max_spread=float(os.getenv("MAX_SPREAD", "0.03")),
        order_size_usd=float(os.getenv("ORDER_SIZE_USD", "10")),
        max_position_usd=float(os.getenv("MAX_POSITION_USD", "30")),
        daily_loss_limit_usd=float(os.getenv("DAILY_LOSS_LIMIT_USD", "20")),
        cooldown_seconds=int(os.getenv("COOLDOWN_SECONDS", "45")),
        profit_take_bps=int(os.getenv("PROFIT_TAKE_BPS", "300")),
        time_stop_seconds=int(os.getenv("TIME_STOP_SECONDS", "180")),
        vol_window=int(os.getenv("VOL_WINDOW", "60")),
        momentum_window=int(os.getenv("MOMENTUM_WINDOW", "40")),
        market_search=os.getenv("MARKET_SEARCH", "Bitcoin Up or Down"),
        window_minutes=int(os.getenv("WINDOW_MINUTES", "5")),
        loop_interval_seconds=float(os.getenv("LOOP_INTERVAL_SECONDS", "1.0")),
        rotate_interval_seconds=int(os.getenv("ROTATE_INTERVAL_SECONDS", "300")),
        quote_print_interval_seconds=int(os.getenv("QUOTE_PRINT_INTERVAL_SECONDS", "60")),
        paper_fill_epsilon=float(os.getenv("PAPER_FILL_EPSILON", "0.0")),
        allow_cross_window_positions=os.getenv("ALLOW_CROSS_WINDOW_POSITIONS", "false").lower() == "true",
        market_discovery_fallback_seconds=int(os.getenv("MARKET_DISCOVERY_FALLBACK_SECONDS", "120")),
    )
