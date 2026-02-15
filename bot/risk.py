from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class RiskState:
    exposure_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    last_trade_ts: datetime | None = None


class RiskManager:
    def __init__(self, max_position_usd: float, daily_loss_limit_usd: float, cooldown_seconds: int) -> None:
        self.max_position_usd = max_position_usd
        self.daily_loss_limit_usd = daily_loss_limit_usd
        self.cooldown_seconds = cooldown_seconds
        self.state = RiskState()
        self.day_start = datetime.now(timezone.utc)

    def reset_if_new_day(self) -> None:
        if datetime.now(timezone.utc) - self.day_start > timedelta(days=1):
            self.state.realized_pnl_usd = 0.0
            self.day_start = datetime.now(timezone.utc)

    def can_open(self, notional_usd: float) -> tuple[bool, str]:
        self.reset_if_new_day()
        if self.state.realized_pnl_usd <= -abs(self.daily_loss_limit_usd):
            return False, "daily_loss_limit_hit"
        if self.state.exposure_usd + notional_usd > self.max_position_usd:
            return False, "max_exposure_hit"
        if self.state.last_trade_ts:
            elapsed = (datetime.now(timezone.utc) - self.state.last_trade_ts).total_seconds()
            if elapsed < self.cooldown_seconds:
                return False, "cooldown_active"
        return True, "ok"

    def on_open(self, notional_usd: float) -> None:
        self.state.exposure_usd += notional_usd
        self.state.last_trade_ts = datetime.now(timezone.utc)

    def on_close(self, notional_usd: float, pnl_usd: float) -> None:
        self.state.exposure_usd = max(self.state.exposure_usd - notional_usd, 0.0)
        self.state.realized_pnl_usd += pnl_usd
        self.state.last_trade_ts = datetime.now(timezone.utc)
