from __future__ import annotations

import math
from collections import deque


class MomentumVolModel:
    def __init__(self, momentum_window: int, vol_window: int) -> None:
        self.momentum_window = momentum_window
        self.vol_window = vol_window

    def predict_up_probability(self, prices: deque[float]) -> float:
        if len(prices) < max(self.momentum_window, self.vol_window) + 2:
            return 0.5

        momentum = (prices[-1] - prices[-self.momentum_window]) / prices[-self.momentum_window]
        returns = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(len(prices) - self.vol_window, len(prices))]
        rv = math.sqrt(sum(r * r for r in returns) / len(returns))

        score = (momentum * 180.0) - (rv * 20.0)
        prob = 1 / (1 + math.exp(-score))
        return min(max(prob, 0.01), 0.99)
