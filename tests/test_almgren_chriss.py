from datetime import datetime, timedelta, timezone

import pytest

from algos.almgren_chriss import (
    AlmgrenChrissAlgorithm,
    AlmgrenChrissParams,
    optimal_holdings_trajectory,
    sensitivity_variants,
)
from algos.twap import TWAPAlgorithm
from backtest.order import ParentOrder

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_parent(duration_minutes=10, quantity=10.0, side="buy"):
    return ParentOrder(
        venue="test", symbol="BTCUSD", side=side, quantity=quantity,
        start_time=START, end_time=START + timedelta(minutes=duration_minutes),
    )


def test_risk_neutral_reduces_exactly_to_twap():
    parent = make_parent(duration_minutes=10, quantity=10.0)
    params = AlmgrenChrissParams(
        temporary_impact=0.01, permanent_impact=1e-5, volatility=0.02, risk_aversion=0.0
    )
    ac_children = AlmgrenChrissAlgorithm(n_slices=5, params=params).slice(parent)
    twap_children = TWAPAlgorithm(n_slices=5).slice(parent)

    for ac, twap in zip(ac_children, twap_children):
        assert ac.timestamp == twap.timestamp
        assert ac.quantity == pytest.approx(twap.quantity)


def test_holdings_trajectory_boundary_conditions():
    params = AlmgrenChrissParams(
        temporary_impact=0.01, permanent_impact=1e-5, volatility=0.02, risk_aversion=1e-6
    )
    holdings = optimal_holdings_trajectory(total_quantity=100.0, n_slices=10, tau=60.0, params=params)
    assert holdings[0] == pytest.approx(100.0)
    assert holdings[-1] == pytest.approx(0.0, abs=1e-6)


def test_holdings_trajectory_is_monotonically_non_increasing():
    params = AlmgrenChrissParams(
        temporary_impact=0.01, permanent_impact=1e-5, volatility=0.3, risk_aversion=0.5
    )
    holdings = optimal_holdings_trajectory(total_quantity=100.0, n_slices=10, tau=60.0, params=params)
    for a, b in zip(holdings, holdings[1:]):
        assert b <= a + 1e-9


def test_positive_risk_aversion_front_loads_execution():
    parent = make_parent(duration_minutes=10, quantity=10.0)
    params = AlmgrenChrissParams(
        temporary_impact=0.01, permanent_impact=1e-5, volatility=0.3, risk_aversion=0.8
    )
    children = AlmgrenChrissAlgorithm(n_slices=5, params=params).slice(parent)
    equal_share = 10.0 / 5

    assert children[0].quantity > equal_share
    assert children[0].quantity > children[-1].quantity


def test_ill_posed_eta_tilde_raises():
    # gamma so large relative to eta/tau that eta - 0.5*gamma*tau <= 0
    params = AlmgrenChrissParams(
        temporary_impact=0.001, permanent_impact=1.0, volatility=0.1, risk_aversion=0.5
    )
    with pytest.raises(ValueError):
        optimal_holdings_trajectory(total_quantity=100.0, n_slices=5, tau=60.0, params=params)


def test_rejects_non_positive_n_slices():
    params = AlmgrenChrissParams(
        temporary_impact=0.01, permanent_impact=0.001, volatility=0.1, risk_aversion=0.1
    )
    with pytest.raises(ValueError):
        AlmgrenChrissAlgorithm(n_slices=0, params=params)


def test_params_reject_invalid_values():
    with pytest.raises(ValueError):
        AlmgrenChrissParams(temporary_impact=0.0, permanent_impact=0.0, volatility=0.1, risk_aversion=0.1)
    with pytest.raises(ValueError):
        AlmgrenChrissParams(temporary_impact=0.01, permanent_impact=-1.0, volatility=0.1, risk_aversion=0.1)
    with pytest.raises(ValueError):
        AlmgrenChrissParams(temporary_impact=0.01, permanent_impact=0.0, volatility=0.1, risk_aversion=-1.0)


def test_sensitivity_variants_perturb_one_parameter_at_a_time():
    base = AlmgrenChrissParams(
        temporary_impact=0.01, permanent_impact=0.002, volatility=0.1, risk_aversion=0.3
    )
    variants = sensitivity_variants(base, pct=0.2)

    assert variants["base"] == base
    assert variants["eta_high"].temporary_impact == pytest.approx(0.012)
    assert variants["eta_high"].permanent_impact == base.permanent_impact
    assert variants["eta_low"].temporary_impact == pytest.approx(0.008)
    assert variants["gamma_high"].permanent_impact == pytest.approx(0.0024)
    assert variants["gamma_high"].temporary_impact == base.temporary_impact
    assert variants["gamma_low"].permanent_impact == pytest.approx(0.0016)
