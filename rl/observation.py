"""State vector for the RL execution policy, built entirely from the real
reconstructed book (`lob/`) plus the agent's own progress through the
current parent order: remaining inventory, time remaining, spread,
order book imbalance, recent realized volatility.
"""

import numpy as np

from lob.order_book import OrderBook

OBSERVATION_DIM = 5
OBSERVATION_NAMES = ("remaining_fraction", "time_fraction", "spread_fraction", "imbalance", "realized_vol")


def build_observation(
    book: OrderBook, remaining_fraction: float, time_fraction: float, realized_vol, imbalance_levels: int = 5
) -> np.ndarray:
    mid = book.mid_price()
    spread = book.spread()
    spread_fraction = (spread / mid) if (spread is not None and mid) else 0.0

    imbalance = book.imbalance(levels=imbalance_levels)
    imbalance = imbalance if imbalance is not None else 0.0

    vol = realized_vol if realized_vol is not None else 0.0

    return np.array(
        [remaining_fraction, time_fraction, spread_fraction, imbalance, vol], dtype=np.float32
    )
