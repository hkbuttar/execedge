"""Per-step reward: negative implementation shortfall (the fill
model's cost convention, same as backtest.metrics.implementation_shortfall)
plus an Almgren-Chriss-consistent risk-aversion penalty on remaining
exposure.

Provable, tested property (tests/test_rl_reward.py): with
`risk_aversion=0`, the sum of `step_reward()` across a full episode
equals exactly `-implementation_shortfall(...).total_cost` computed by
`backtest.metrics` on the same fills -- the RL reward signal is the same
objective every other algorithm in this project is scored on, not a
separate proxy for it. `risk_aversion > 0` adds a variance-penalty term on
top, mirroring how Almgren-Chriss's own objective adds
`risk_aversion * variance` beyond expected cost -- not something
`implementation_shortfall` itself accounts for.
"""

from backtest.order import Fill


def step_execution_cost(fills: list[Fill], arrival_price: float, side_sign: int) -> float:
    """Same convention as backtest.metrics.implementation_shortfall's
    executed_cost term: positive means this step's fills cost more than
    the arrival price (bad), for either side via side_sign."""
    return sum((f.price - arrival_price) * f.quantity * side_sign for f in fills)


def risk_penalty(remaining_after: float, sigma: float, tau: float, risk_aversion: float) -> float:
    """Almgren-Chriss's own variance term, per-interval: risk_aversion *
    sigma^2 * remaining_inventory^2 * tau. Zero when risk_aversion=0."""
    return risk_aversion * (sigma ** 2) * (remaining_after ** 2) * tau


def step_reward(
    fills: list[Fill],
    arrival_price: float,
    side_sign: int,
    remaining_after: float,
    sigma: float,
    tau: float,
    risk_aversion: float,
    is_terminal: bool = False,
    unfilled_at_terminal: float = 0.0,
    end_price: float = None,
) -> float:
    cost = step_execution_cost(fills, arrival_price, side_sign)
    reward = -cost - risk_penalty(remaining_after, sigma, tau, risk_aversion)

    if is_terminal and unfilled_at_terminal > 0:
        if end_price is None:
            raise ValueError("end_price is required when unfilled_at_terminal > 0")
        opportunity_cost = unfilled_at_terminal * (end_price - arrival_price) * side_sign
        reward -= opportunity_cost

    return reward
