from __future__ import annotations

from bot.types import Decision, Signal


def choose_signal(p_up_model: float, up_mid: float, edge_min: float, max_spread: float, up_spread: float, down_spread: float) -> Signal:
    p_up_mkt = up_mid
    p_down_mkt = max(1 - p_up_mkt, 0.0)
    edge_up = p_up_model - p_up_mkt
    edge_down = (1 - p_up_model) - p_down_mkt

    if up_spread > max_spread or down_spread > max_spread:
        return Signal(p_up_model, p_up_mkt, p_down_mkt, edge_up, edge_down, max(edge_up, edge_down), Decision.HOLD, "spread_too_wide")

    if edge_up >= edge_min:
        return Signal(p_up_model, p_up_mkt, p_down_mkt, edge_up, edge_down, edge_up, Decision.BUY_UP, "edge_up")

    if edge_down >= edge_min:
        return Signal(p_up_model, p_up_mkt, p_down_mkt, edge_up, edge_down, edge_down, Decision.BUY_DOWN, "edge_down")

    return Signal(p_up_model, p_up_mkt, p_down_mkt, edge_up, edge_down, max(edge_up, edge_down), Decision.HOLD, "edge_too_low")
