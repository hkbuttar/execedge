"""Implementation shortfall (Perold, 1988): the core benchmark metric for
every algorithm this project compares.

Total shortfall = executed cost + opportunity cost:
  - executed cost: for each fill, (fill_price - arrival_price) * qty * side_sign
    -- positive means the fill cost more than the price when the parent
    order arrived (bad for a buy; mirrored for a sell via side_sign).
  - opportunity cost: any quantity never filled, valued at the price
    when the parent order's window ended vs. the arrival price. This
    charges (or credits) the order for not completing, which is what
    makes shortfall comparable across algorithms that fill different
    fractions of the parent order.
"""

from dataclasses import dataclass

from backtest.order import Fill, ParentOrder


@dataclass
class ShortfallResult:
    executed_quantity: float
    unfilled_quantity: float
    executed_cost: float
    opportunity_cost: float
    total_cost: float
    total_cost_bps: float


def implementation_shortfall(
    parent: ParentOrder, fills: list[Fill], arrival_price: float, end_price: float
) -> ShortfallResult:
    side_sign = parent.side_sign

    executed_quantity = sum(f.quantity for f in fills)
    executed_cost = sum((f.price - arrival_price) * f.quantity * side_sign for f in fills)

    unfilled_quantity = parent.quantity - executed_quantity
    opportunity_cost = unfilled_quantity * (end_price - arrival_price) * side_sign

    total_cost = executed_cost + opportunity_cost
    notional = arrival_price * parent.quantity
    total_cost_bps = (total_cost / notional) * 1e4 if notional > 0 else 0.0

    return ShortfallResult(
        executed_quantity=executed_quantity,
        unfilled_quantity=unfilled_quantity,
        executed_cost=executed_cost,
        opportunity_cost=opportunity_cost,
        total_cost=total_cost,
        total_cost_bps=total_cost_bps,
    )
