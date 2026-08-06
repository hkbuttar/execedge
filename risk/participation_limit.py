"""Participation-rate limit: a hard cap on how much of a child order can
execute relative to real historical volume in its time window, checked
against `data.fetch_volume`'s real data (via `HistoricalVolumeLookup`).

This is a risk control, not a smarter algorithm: quantity above the cap
is simply not submitted for that child order, not rescheduled or
redistributed to later slices. The unfilled remainder flows into the same
implementation-shortfall opportunity-cost accounting every other
under-filled order in this project already uses (backtest/metrics.py) --
exceeding the limit has a real, visible cost, which is the point of a
limit existing at all.
"""

from dataclasses import dataclass, replace
from datetime import datetime

from backtest.order import ChildOrder
from risk.volume_lookup import HistoricalVolumeLookup


@dataclass
class ParticipationLimiter:
    max_participation_rate: float  # e.g. 0.1 = never more than 10% of real volume in the window
    volume_lookup: HistoricalVolumeLookup

    def __post_init__(self):
        if not 0 < self.max_participation_rate <= 1:
            raise ValueError(
                f"max_participation_rate must be in (0, 1], got {self.max_participation_rate}"
            )

    def cap(self, child: ChildOrder, window_end: datetime) -> ChildOrder:
        """Returns `child` unchanged if within the limit, or a copy with
        reduced quantity if not. `window_end` is the end of the real-time
        interval this child order represents (typically the next child
        order's timestamp, or the parent order's end_time for the last
        one) -- the limiter needs a window to look up real volume for,
        not just a single instant.
        """
        real_volume = self.volume_lookup.volume_between(child.timestamp, window_end)
        max_quantity = self.max_participation_rate * real_volume
        if child.quantity <= max_quantity:
            return child
        return replace(child, quantity=max(max_quantity, 0.0))
