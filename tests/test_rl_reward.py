from datetime import datetime, timedelta, timezone

import pytest

from backtest.metrics import implementation_shortfall
from backtest.order import Fill, ParentOrder
from rl.reward import risk_penalty, step_execution_cost, step_reward

NOW = datetime.now(timezone.utc)


def test_step_rewards_sum_to_negative_implementation_shortfall_when_risk_neutral():
    """The core consistency property this reward function is built for:
    with risk_aversion=0, per-step rewards accumulated across a full
    episode equal exactly -implementation_shortfall(...).total_cost
    computed independently by backtest.metrics on the same fills."""
    arrival_price, end_price, side_sign = 100.0, 105.0, 1  # buy

    step1_fills = [Fill(timestamp=NOW, price=101.0, quantity=3.0)]
    step2_fills = [Fill(timestamp=NOW, price=102.0, quantity=2.0)]
    step3_fills = [Fill(timestamp=NOW, price=103.0, quantity=3.0)]  # terminal, 1.0 left unfilled

    r1 = step_reward(step1_fills, arrival_price, side_sign, remaining_after=6.0, sigma=0, tau=1, risk_aversion=0)
    r2 = step_reward(step2_fills, arrival_price, side_sign, remaining_after=4.0, sigma=0, tau=1, risk_aversion=0)
    r3 = step_reward(
        step3_fills, arrival_price, side_sign, remaining_after=1.0, sigma=0, tau=1, risk_aversion=0,
        is_terminal=True, unfilled_at_terminal=1.0, end_price=end_price,
    )
    total_reward = r1 + r2 + r3

    parent = ParentOrder(
        venue="test", symbol="BTCUSD", side="buy", quantity=9.0,
        start_time=NOW, end_time=NOW + timedelta(seconds=1),
    )
    all_fills = step1_fills + step2_fills + step3_fills
    shortfall = implementation_shortfall(parent, all_fills, arrival_price, end_price)

    assert total_reward == pytest.approx(-shortfall.total_cost)


def test_step_execution_cost_sign_convention():
    buy_fills = [Fill(timestamp=NOW, price=101.0, quantity=2.0)]
    assert step_execution_cost(buy_fills, arrival_price=100.0, side_sign=1) == pytest.approx(2.0)

    sell_fills = [Fill(timestamp=NOW, price=99.0, quantity=2.0)]
    assert step_execution_cost(sell_fills, arrival_price=100.0, side_sign=-1) == pytest.approx(2.0)


def test_risk_penalty_scales_with_remaining_squared_sigma_and_tau():
    base = risk_penalty(remaining_after=10.0, sigma=0.1, tau=1.0, risk_aversion=0.5)
    assert risk_penalty(remaining_after=20.0, sigma=0.1, tau=1.0, risk_aversion=0.5) == pytest.approx(base * 4)
    assert risk_penalty(remaining_after=10.0, sigma=0.2, tau=1.0, risk_aversion=0.5) == pytest.approx(base * 4)
    assert risk_penalty(remaining_after=10.0, sigma=0.1, tau=2.0, risk_aversion=0.5) == pytest.approx(base * 2)
    assert risk_penalty(remaining_after=10.0, sigma=0.1, tau=1.0, risk_aversion=0.0) == 0.0


def test_terminal_reward_requires_end_price_when_unfilled():
    with pytest.raises(ValueError):
        step_reward(
            [], arrival_price=100.0, side_sign=1, remaining_after=5.0, sigma=0, tau=1, risk_aversion=0,
            is_terminal=True, unfilled_at_terminal=5.0, end_price=None,
        )
