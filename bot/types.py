from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Mode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class Decision(str, Enum):
    BUY_UP = "buy_up"
    BUY_DOWN = "buy_down"
    HOLD = "hold"


@dataclass(slots=True)
class MarketQuote:
    token_id: str
    bid: float
    ask: float
    ts: datetime

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2 if self.bid and self.ask else 0.0

    @property
    def spread(self) -> float:
        return max(self.ask - self.bid, 0.0)


@dataclass(slots=True)
class Signal:
    p_up_model: float
    p_up_mkt: float
    p_down_mkt: float
    edge_up: float
    edge_down: float
    edge: float
    decision: Decision
    reason_code: str


@dataclass(slots=True)
class Position:
    market_slug: str
    token_id: str
    qty: float
    entry_price: float
    entry_ts: datetime
    side: str = "buy"
    order_id: str | None = None
    metadata: dict = field(default_factory=dict)
