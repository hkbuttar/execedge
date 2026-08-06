"""VWAP: slice proportional to a real historical volume curve
(data/volume_profile.py) rather than equal time buckets. Same regular
time granularity as TWAP -- n_slices equal-duration buckets across the
window -- but each bucket's size is weighted by its hour-of-day's real
historical volume share instead of 1/n_slices.

If Step 3 found no significant time-of-day effect for this venue,
`hourly_weights` will be flat (1/24 every hour) and VWAP degenerates
exactly to TWAP -- which is the correct behavior, not a bug: there's
nothing in the real data to shape the curve around, so it shouldn't
pretend otherwise.

One resolution limit worth stating plainly: the profile has hourly
granularity. A parent order whose whole window sits inside a single hour
gets a flat weighting regardless of the profile, since there's no finer
real signal to differentiate the slices within that hour.
"""

from backtest.algorithm import ExecutionAlgorithm
from backtest.order import ChildOrder, ParentOrder


class VWAPAlgorithm(ExecutionAlgorithm):
    def __init__(self, n_slices: int, hourly_weights: dict):
        if n_slices < 1:
            raise ValueError(f"n_slices must be >= 1, got {n_slices}")
        if set(hourly_weights) != set(range(24)):
            raise ValueError("hourly_weights must have exactly one entry per hour, 0-23")
        self.n_slices = n_slices
        self.hourly_weights = hourly_weights

    def slice(self, parent: ParentOrder) -> list[ChildOrder]:
        duration = parent.end_time - parent.start_time
        interval = duration / self.n_slices
        timestamps = [parent.start_time + i * interval for i in range(self.n_slices)]

        raw_weights = [self.hourly_weights[ts.hour] for ts in timestamps]
        total_weight = sum(raw_weights)
        if total_weight <= 0:
            raise ValueError(
                "all hours spanned by this parent order have zero volume weight; "
                "cannot proportionally slice against an all-zero profile"
            )

        return [
            ChildOrder(
                timestamp=ts,
                quantity=parent.quantity * w / total_weight,
                side=parent.side,
            )
            for ts, w in zip(timestamps, raw_weights)
        ]
