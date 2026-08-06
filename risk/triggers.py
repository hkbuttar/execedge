"""Kill-switch trigger conditions: given the real-time state of a running
execution, decide whether to halt. The kill switch itself (kill_switch.py)
is trigger-agnostic -- these are the two conditions this project ties to
it, both computed from data the simulator already has on hand at each
step, no new data source needed.
"""

from dataclasses import dataclass


@dataclass
class RiskState:
    realized_vol: float | None  # from lob.features.RealizedVolTracker, updated per step
    cumulative_cost_bps: float  # implementation-shortfall cost so far, in bps of arrival notional


def volatility_trigger(max_realized_vol: float):
    """Halts if recent realized volatility (real book mid-price returns,
    lob.features.RealizedVolTracker) exceeds `max_realized_vol` --
    "the market's too chaotic right now, stop trading into it."
    """
    def check(state: RiskState) -> str | None:
        if state.realized_vol is not None and state.realized_vol > max_realized_vol:
            return f"realized volatility {state.realized_vol:.6g} exceeded max {max_realized_vol:.6g}"
        return None

    return check


def shortfall_trigger(max_cumulative_cost_bps: float):
    """Halts if cumulative implementation-shortfall cost so far exceeds
    `max_cumulative_cost_bps` -- "this execution is bleeding too much,
    stop digging."
    """
    def check(state: RiskState) -> str | None:
        if state.cumulative_cost_bps > max_cumulative_cost_bps:
            return (
                f"cumulative cost {state.cumulative_cost_bps:.2f} bps exceeded "
                f"max {max_cumulative_cost_bps:.2f} bps"
            )
        return None

    return check
