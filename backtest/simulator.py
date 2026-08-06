"""The order-slicing harness: given a parent order and an algorithm,
slice into child orders, submit each against the real reconstructed book
at its real timestamp via the fill model, and score the result against
implementation shortfall.
"""

from dataclasses import dataclass

from backtest.algorithm import ExecutionAlgorithm
from backtest.book_history import BookHistoryReader
from backtest.fill_model import FillModel
from backtest.metrics import ShortfallResult, implementation_shortfall
from backtest.order import ChildOrder, Fill, ParentOrder


@dataclass
class BacktestResult:
    parent: ParentOrder
    child_orders: list[ChildOrder]
    fills: list[Fill]
    arrival_price: float
    end_price: float
    shortfall: ShortfallResult


class OrderSlicingSimulator:
    def __init__(self, book_history: BookHistoryReader, fill_model: FillModel):
        self.book_history = book_history
        self.fill_model = fill_model

    def run(self, parent: ParentOrder, algorithm: ExecutionAlgorithm) -> BacktestResult:
        arrival_price = self.book_history.book_at_or_before(parent.start_time).mid_price()
        end_price = self.book_history.book_at_or_before(parent.end_time).mid_price()
        if arrival_price is None or end_price is None:
            raise ValueError(
                "book history has no valid two-sided quote at the order's start/end time"
            )

        child_orders = algorithm.slice(parent)
        run = self.fill_model.new_run()

        fills: list[Fill] = []
        for child in child_orders:
            book = self.book_history.book_at_or_before(child.timestamp)
            result = run.execute(child, book)
            fills.extend(result.fills)

        shortfall = implementation_shortfall(parent, fills, arrival_price, end_price)

        return BacktestResult(
            parent=parent,
            child_orders=child_orders,
            fills=fills,
            arrival_price=arrival_price,
            end_price=end_price,
            shortfall=shortfall,
        )
