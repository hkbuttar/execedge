"""Execution algorithm interface: given a parent order, produce the child
order schedule the simulator will submit against the real book history.

Deliberately static/up-front for now -- `slice()` returns the whole
schedule before any fills happen. TWAP (Step 5), VWAP (Step 6), and
Almgren-Chriss (Step 7) all fit this shape; a strategy that wants to
re-slice dynamically based on fills-so-far would need the interface
extended, which isn't done here since nothing in this project needs it
yet.
"""

from abc import ABC, abstractmethod

from backtest.order import ChildOrder, ParentOrder


class ExecutionAlgorithm(ABC):
    @abstractmethod
    def slice(self, parent: ParentOrder) -> list[ChildOrder]:
        """Return child orders in ascending timestamp order, each within
        [parent.start_time, parent.end_time], summing to parent.quantity."""


class NaiveMarketOrderAlgorithm(ExecutionAlgorithm):
    """Dumps the entire parent order as one child order at start_time --
    maximum market impact, zero timing risk. Not a real execution
    strategy; exists to exercise the simulator/fill-model harness end to
    end before Step 5's TWAP (the actual control) lands.
    """

    def slice(self, parent: ParentOrder) -> list[ChildOrder]:
        return [ChildOrder(timestamp=parent.start_time, quantity=parent.quantity, side=parent.side)]
