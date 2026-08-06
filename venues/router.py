"""Venue-routing decision, layered *alongside* an algorithm's slicing
decision rather than baked into it -- an algorithm's `.slice()` (Step
5-8) stays venue-agnostic; `venues/multi_venue_simulator.py` asks a
router which venue each already-sized, already-timed child order should
go to. This mirrors how Step 9's risk layer was added as a cross-cutting
wrapper around the simulator rather than a rewrite of every algorithm.
"""

from abc import ABC, abstractmethod

from backtest.order import ChildOrder
from lob.order_book import OrderBook
from venues.fees import FeeSchedule


class VenueRouter(ABC):
    @abstractmethod
    def choose(
        self, child: ChildOrder, books: dict[str, OrderBook], fee_schedules: dict[str, FeeSchedule]
    ) -> str:
        """Return which venue name (a key of `books`) to route `child` to."""


class SingleVenueRouter(VenueRouter):
    """Always the same venue -- no routing decision at all. The baseline
    "naive" comparison point for whether smart routing helps."""

    def __init__(self, venue: str):
        self.venue = venue

    def choose(self, child: ChildOrder, books: dict, fee_schedules: dict) -> str:
        return self.venue


class BestEffectivePriceRouter(VenueRouter):
    """Routes to whichever venue offers the best all-in price -- real
    quoted touch price plus that venue's own real taker fee -- for this
    child order's side, at this child order's real timestamp. "Smart"
    routing as this project defines it: comparing real quotes and real
    fees across venues at the same real moment, not a forecast.
    """

    def choose(self, child: ChildOrder, books: dict, fee_schedules: dict) -> str:
        side_sign = 1 if child.side == "buy" else -1

        best_venue = None
        best_signed_price = None
        for venue, book in books.items():
            touch_price = book.best_ask() if child.side == "buy" else book.best_bid()
            if touch_price is None:
                continue
            fee_bps = fee_schedules[venue].taker_fee_bps
            effective_price = touch_price * (1 + side_sign * fee_bps / 1e4)
            signed_price = effective_price * side_sign  # lower is always better in this space
            if best_signed_price is None or signed_price < best_signed_price:
                best_signed_price = signed_price
                best_venue = venue

        if best_venue is None:
            raise ValueError("no venue has a valid touch price at this child order's timestamp")
        return best_venue
