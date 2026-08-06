"""Parent/child order and fill records for the order-slicing simulator."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ParentOrder:
    venue: str
    symbol: str
    side: str  # "buy" or "sell"
    quantity: float
    start_time: datetime
    end_time: datetime

    def __post_init__(self):
        if self.side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {self.side!r}")
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")

    @property
    def side_sign(self) -> int:
        """+1 for buy (paying more than arrival hurts), -1 for sell
        (receiving less than arrival hurts) -- the sign convention used
        throughout backtest/metrics.py."""
        return 1 if self.side == "buy" else -1


@dataclass
class ChildOrder:
    timestamp: datetime
    quantity: float
    side: str  # always the parent order's side; carried per-child for a self-contained record


@dataclass
class Fill:
    timestamp: datetime
    price: float
    quantity: float
