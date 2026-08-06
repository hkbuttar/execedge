"""The one necessary, clearly-flagged simplification layered on top of
otherwise-real data: a hypothetical parent order never actually existed
in the historical record, so something has to decide whether/at what
price/how much each child order fills, and how much our own hypothetical
presence would have moved the price beyond what the real resting book
shows.

Mechanics, stated plainly:

1. **Book walk against real resting liquidity.** A child order consumes
   real recorded price levels in order (best first) exactly as if it had
   rested against that book -- this part isn't a simplification, it's
   arithmetic against real depth.
2. **Temporary impact.** On top of the walked price, a single
   participation-rate-scaled cost is added to every fill from that child
   order: `temp_impact_coef * sqrt(child_qty / visible_liquidity)`, in the
   direction that hurts the order (buys pay up, sells receive less). This
   is a square-root-law-style functional form (see data/README.md's
   Almgren-Chriss placeholder section) applied per child order, not per
   individual level consumed within it -- a modeling choice made for
   simplicity/auditability, not because per-level impact wouldn't be more
   realistic.
3. **Permanent impact.** After each child order, a price offset
   accumulates for the rest of that *same parent order's* execution
   (`FillModelRun.permanent_offset`), representing a lasting shift in the
   reference price due to cumulative footprint. It is never written back
   into the shared real `OrderBook` -- the real historical record for
   other backtests, and for other child orders at the same historical
   timestamp from a different simulated run, stays untouched.

`temporary_impact_coef` / `permanent_impact_coef` have no default: Step 1
deliberately didn't hardcode literature impact numbers without a proper
citation, and Step 7 is where literature-derived and empirically-estimated
coefficients get produced and compared. Pass `0.0` for both to isolate
pure book-walk behavior (e.g. for testing) -- that's an explicit choice,
not a silent one.
"""

import math
from dataclasses import dataclass

from backtest.order import ChildOrder, Fill
from lob.order_book import OrderBook


@dataclass
class ExecutionResult:
    fills: list[Fill]
    unfilled_quantity: float


class FillModel:
    def __init__(self, temporary_impact_coef: float, permanent_impact_coef: float):
        self.temporary_impact_coef = temporary_impact_coef
        self.permanent_impact_coef = permanent_impact_coef

    def new_run(self) -> "FillModelRun":
        """One `FillModelRun` per parent order: permanent impact accumulates
        across that order's child orders only, then is discarded."""
        return FillModelRun(self)


class FillModelRun:
    def __init__(self, model: FillModel):
        self.model = model
        self.permanent_offset = 0.0

    def execute(self, child: ChildOrder, book: OrderBook) -> ExecutionResult:
        side_sign = 1 if child.side == "buy" else -1
        book_side = "ask" if child.side == "buy" else "bid"
        levels = book.top_levels(book_side, n=len(book.asks if child.side == "buy" else book.bids))

        remaining = child.quantity
        raw_fills = []  # (price, qty) before impact adjustment
        for price, level_qty in levels:
            if remaining <= 0:
                break
            take = min(remaining, level_qty)
            raw_fills.append((price, take))
            remaining -= take
        unfilled = remaining

        total_visible = sum(qty for _, qty in levels)
        participation = (child.quantity / total_visible) if total_visible > 0 else 1.0
        temp_impact_frac = self.model.temporary_impact_coef * math.sqrt(participation)

        fills = [
            Fill(
                timestamp=child.timestamp,
                price=price * (1 + side_sign * temp_impact_frac) + side_sign * self.permanent_offset,
                quantity=qty,
            )
            for price, qty in raw_fills
        ]

        if raw_fills:
            filled_qty = sum(qty for _, qty in raw_fills)
            avg_price = sum(price * qty for price, qty in raw_fills) / filled_qty
            perm_impact_frac = self.model.permanent_impact_coef * math.sqrt(participation)
            self.permanent_offset += side_sign * perm_impact_frac * avg_price

        return ExecutionResult(fills=fills, unfilled_quantity=unfilled)
