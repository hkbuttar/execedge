"""The order-slicing harness: given a parent order and an algorithm,
slice into child orders, submit each against the real reconstructed book
at its real timestamp via the fill model, and score the result against
implementation shortfall.

Optionally applies Step 9's risk layer (risk/) as each child order is
about to be submitted -- a participation-rate cap and/or a kill switch
that halts all remaining child orders for the rest of this run. Both are
cross-cutting: they wrap *any* algorithm's output here, in the one place
that actually walks child orders forward in real time, rather than being
baked into TWAP/VWAP/AC/RL individually. `ExecutionAlgorithm.slice()` is
static/up-front (see backtest/algorithm.py), so this is also the only
place a genuinely real-time control -- one that reacts to conditions as
of each child order's own moment, not just at slice-generation time --
can actually live in this project's current design.
"""

from dataclasses import dataclass
from datetime import datetime

from backtest.algorithm import ExecutionAlgorithm
from backtest.book_history import BookHistoryReader
from backtest.fill_model import FillModel
from backtest.metrics import ShortfallResult, implementation_shortfall
from backtest.order import ChildOrder, Fill, ParentOrder
from lob.features import RealizedVolTracker
from risk.kill_switch import KillSwitch
from risk.participation_limit import ParticipationLimiter
from risk.triggers import RiskState


@dataclass
class BacktestResult:
    parent: ParentOrder
    child_orders: list[ChildOrder]
    fills: list[Fill]
    arrival_price: float
    end_price: float
    shortfall: ShortfallResult
    halted_at: datetime | None = None  # set if the kill switch cut this run short


class OrderSlicingSimulator:
    def __init__(
        self,
        book_history: BookHistoryReader,
        fill_model: FillModel,
        participation_limiter: ParticipationLimiter | None = None,
        kill_switch: KillSwitch | None = None,
        kill_switch_triggers: list | None = None,
    ):
        self.book_history = book_history
        self.fill_model = fill_model
        self.participation_limiter = participation_limiter
        self.kill_switch = kill_switch
        self.kill_switch_triggers = kill_switch_triggers or []

    def run(self, parent: ParentOrder, algorithm: ExecutionAlgorithm) -> BacktestResult:
        arrival_price = self.book_history.book_at_or_before(parent.start_time).mid_price()
        end_price = self.book_history.book_at_or_before(parent.end_time).mid_price()
        if arrival_price is None or end_price is None:
            raise ValueError(
                "book history has no valid two-sided quote at the order's start/end time"
            )

        child_orders = algorithm.slice(parent)
        run = self.fill_model.new_run()
        vol_tracker = RealizedVolTracker()
        notional = arrival_price * parent.quantity

        fills: list[Fill] = []
        halted_at: datetime | None = None

        for i, child in enumerate(child_orders):
            if self.kill_switch is not None and self.kill_switch.is_tripped:
                halted_at = child.timestamp
                break

            book = self.book_history.book_at_or_before(child.timestamp)
            vol_tracker.update(book.mid_price())

            if self.kill_switch is not None and self.kill_switch_triggers:
                cumulative_cost = sum(
                    (f.price - arrival_price) * f.quantity * parent.side_sign for f in fills
                )
                cumulative_cost_bps = (cumulative_cost / notional) * 1e4 if notional > 0 else 0.0
                state = RiskState(realized_vol=vol_tracker.value(), cumulative_cost_bps=cumulative_cost_bps)
                for trigger in self.kill_switch_triggers:
                    reason = trigger(state)
                    if reason:
                        self.kill_switch.trip(reason, child.timestamp)
                        break
                if self.kill_switch.is_tripped:
                    halted_at = child.timestamp
                    break

            effective_child = child
            if self.participation_limiter is not None:
                window_end = (
                    child_orders[i + 1].timestamp if i + 1 < len(child_orders) else parent.end_time
                )
                effective_child = self.participation_limiter.cap(child, window_end)

            result = run.execute(effective_child, book)
            fills.extend(result.fills)

        shortfall = implementation_shortfall(parent, fills, arrival_price, end_price)

        return BacktestResult(
            parent=parent,
            child_orders=child_orders,
            fills=fills,
            arrival_price=arrival_price,
            end_price=end_price,
            shortfall=shortfall,
            halted_at=halted_at,
        )
