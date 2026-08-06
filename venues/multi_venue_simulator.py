"""Order-slicing simulator extended across three real venues: an
algorithm's `.slice()` output (venue-agnostic sizing/timing, unchanged
from TWAP/VWAP/AC/RL) gets routed per child order via a `VenueRouter`
(router.py), executed against *that* venue's own real recorded book, and
charged that venue's own real taker fee (fees.py) -- every fill in this
project's fill model crosses the spread, so every fill is a taker fill.

Implementation shortfall's arrival/end price benchmark still comes from a
single reference venue (`parent.venue`), even when child orders route
elsewhere -- mirroring how a real desk benchmarks execution against one
reference price regardless of which venue actually filled the order. This
is a deliberate choice: the alternative (a synthetic "best of all venues"
consolidated reference price) would make the benchmark itself dependent
on the same routing question being evaluated, muddying exactly what's
being measured.
"""

from dataclasses import dataclass, replace

from backtest.algorithm import ExecutionAlgorithm
from backtest.fill_model import FillModel
from backtest.metrics import ShortfallResult, implementation_shortfall
from backtest.order import ChildOrder, Fill, ParentOrder
from venues.router import VenueRouter


@dataclass
class MultiVenueBacktestResult:
    parent: ParentOrder
    child_orders: list[ChildOrder]
    fills_by_venue: dict  # venue -> list[Fill], fees already applied
    routing_decisions: list  # [(timestamp, venue), ...] in child-order order
    arrival_price: float
    end_price: float
    shortfall: ShortfallResult

    @property
    def all_fills(self) -> list[Fill]:
        return [fill for fills in self.fills_by_venue.values() for fill in fills]


class MultiVenueSimulator:
    def __init__(
        self,
        book_histories: dict,  # venue -> BookHistoryReader
        fee_schedules: dict,  # venue -> FeeSchedule
        fill_model: FillModel,
        router: VenueRouter,
    ):
        self.book_histories = book_histories
        self.fee_schedules = fee_schedules
        self.fill_model = fill_model
        self.router = router

    def run(self, parent: ParentOrder, algorithm: ExecutionAlgorithm) -> MultiVenueBacktestResult:
        reference_history = self.book_histories[parent.venue]
        arrival_price = reference_history.book_at_or_before(parent.start_time).mid_price()
        end_price = reference_history.book_at_or_before(parent.end_time).mid_price()
        if arrival_price is None or end_price is None:
            raise ValueError(
                "reference venue's book history has no valid two-sided quote at "
                "the order's start/end time"
            )

        child_orders = algorithm.slice(parent)
        side_sign = 1 if parent.side == "buy" else -1

        runs_by_venue = {venue: self.fill_model.new_run() for venue in self.book_histories}
        fills_by_venue: dict = {venue: [] for venue in self.book_histories}
        routing_decisions = []

        for child in child_orders:
            books_at_t = {
                venue: history.book_at_or_before(child.timestamp)
                for venue, history in self.book_histories.items()
            }
            chosen_venue = self.router.choose(child, books_at_t, self.fee_schedules)
            routing_decisions.append((child.timestamp, chosen_venue))

            result = runs_by_venue[chosen_venue].execute(child, books_at_t[chosen_venue])

            taker_fee_bps = self.fee_schedules[chosen_venue].taker_fee_bps
            for fill in result.fills:
                fee_adjusted_price = fill.price * (1 + side_sign * taker_fee_bps / 1e4)
                fills_by_venue[chosen_venue].append(replace(fill, price=fee_adjusted_price))

        all_fills = [fill for fills in fills_by_venue.values() for fill in fills]
        shortfall = implementation_shortfall(parent, all_fills, arrival_price, end_price)

        return MultiVenueBacktestResult(
            parent=parent,
            child_orders=child_orders,
            fills_by_venue=fills_by_venue,
            routing_decisions=routing_decisions,
            arrival_price=arrival_price,
            end_price=end_price,
            shortfall=shortfall,
        )
