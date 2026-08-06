"""Wraps a trained RL policy as a backtest.algorithm.ExecutionAlgorithm,
so it plugs into the exact same simulator and implementation-shortfall
metrics every other algorithm (TWAP/VWAP/Almgren-Chriss) is compared
through -- see rl/evaluate.py. No separate RL-only scoring path.

Same regular n_steps interval convention as TWAP/VWAP/Almgren-Chriss, for
direct comparability.
"""

from datetime import timedelta

from backtest.algorithm import ExecutionAlgorithm
from backtest.book_history import BookHistoryReader
from backtest.order import ChildOrder, ParentOrder
from lob.features import RealizedVolTracker
from rl.action_space import action_to_fraction
from rl.observation import build_observation


class TrainedPolicyAlgorithm(ExecutionAlgorithm):
    def __init__(self, model, book_history: BookHistoryReader, n_steps: int, deterministic: bool = True):
        self.model = model
        self.book_history = book_history
        self.n_steps = n_steps
        self.deterministic = deterministic

    def slice(self, parent: ParentOrder) -> list:
        tau = (parent.end_time - parent.start_time).total_seconds() / self.n_steps
        remaining = parent.quantity
        vol_tracker = RealizedVolTracker()
        children = []

        for step_idx in range(self.n_steps):
            timestamp = parent.start_time + timedelta(seconds=tau * step_idx)
            book = self.book_history.book_at_or_before(timestamp)
            vol_tracker.update(book.mid_price())

            remaining_fraction = remaining / parent.quantity if parent.quantity > 0 else 0.0
            time_fraction = step_idx / self.n_steps
            obs = build_observation(book, remaining_fraction, time_fraction, vol_tracker.value())

            action, _ = self.model.predict(obs, deterministic=self.deterministic)
            qty = min(remaining, action_to_fraction(int(action)) * remaining)

            children.append(ChildOrder(timestamp=timestamp, quantity=qty, side=parent.side))
            remaining -= qty

        # If the policy chose to leave inventory unfilled through the
        # whole horizon, it is NOT force-dumped here -- it's charged via
        # implementation shortfall's opportunity-cost term, same as any
        # other algorithm whose fills fall short of the real book's
        # available depth. This is a genuine behavioral difference from
        # TWAP/VWAP/AC, whose slice() output always sums to exactly
        # parent.quantity by construction; RL's doesn't have to.
        return children
