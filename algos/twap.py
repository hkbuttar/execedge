"""TWAP: equal-size slices at regular time intervals. The control every
other algorithm in this project (VWAP, Almgren-Chriss, RL) is benchmarked
against -- it doesn't use the real volume profile, the real book's
current depth, or any impact model to decide sizing; it just spreads the
order flat across the window. Sizing that turns out to beat TWAP is
demonstrating it exploited something (volume shape, impact awareness)
that TWAP deliberately ignores.
"""

from backtest.algorithm import ExecutionAlgorithm
from backtest.order import ChildOrder, ParentOrder


class TWAPAlgorithm(ExecutionAlgorithm):
    def __init__(self, n_slices: int):
        if n_slices < 1:
            raise ValueError(f"n_slices must be >= 1, got {n_slices}")
        self.n_slices = n_slices

    def slice(self, parent: ParentOrder) -> list[ChildOrder]:
        duration = parent.end_time - parent.start_time
        interval = duration / self.n_slices
        child_quantity = parent.quantity / self.n_slices
        return [
            ChildOrder(
                timestamp=parent.start_time + i * interval,
                quantity=child_quantity,
                side=parent.side,
            )
            for i in range(self.n_slices)
        ]
