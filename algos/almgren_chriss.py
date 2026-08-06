"""Almgren-Chriss (2000) closed-form optimal execution trajectory.

Citation: Almgren, R., Chriss, N. (2000). "Optimal Execution of Portfolio
Transactions." Journal of Risk, 3, 5-39.

The model assumes linear impact -- permanent g(v) = gamma*v, temporary
h(v) = eta*v, for trading rate v -- and minimizes expected cost plus
`risk_aversion` times cost variance over a fixed horizon split into
`n_slices` equal intervals of length tau. The optimal remaining-holdings
trajectory at interval boundary t_j is:

    x_j = X * sinh(kappa*(T - t_j)) / sinh(kappa*T)

where kappa solves cosh(kappa*tau) = 1 + tau^2 * kappa_tilde^2 / 2, i.e.
kappa = arccosh(1 + tau^2*kappa_tilde^2/2) / tau, and

    kappa_tilde^2 = risk_aversion * sigma^2 / eta_tilde
    eta_tilde = eta - 0.5*gamma*tau

(formulas cross-checked against the paper's own closed-form summary and a
second independent source before implementing, given how central this
equation is to the whole comparison).

Two special cases worth knowing, both used as correctness tests:
  - risk_aversion = 0 (risk-neutral): kappa = 0, and the sinh/sinh ratio's
    well-defined limit is (T-t_j)/T -- a perfectly linear trajectory,
    i.e. equal-sized slices at equal intervals. This makes
    AlmgrenChrissAlgorithm(risk_aversion=0) produce an *identical* child
    order schedule to TWAPAlgorithm with the same n_slices -- TWAP is the
    risk-neutral special case of Almgren-Chriss, not just a separately
    "simpler" strategy.
  - risk_aversion > 0: the trajectory front-loads execution (sells/buys
    more in the earlier intervals) to reduce exposure to price risk over
    the remaining horizon, at the cost of more market impact.
"""

import math
from dataclasses import dataclass, replace
from datetime import timedelta

from backtest.algorithm import ExecutionAlgorithm
from backtest.order import ChildOrder, ParentOrder


@dataclass(frozen=True)
class AlmgrenChrissParams:
    temporary_impact: float  # eta: h(v) = eta*v, price units per (size/time)
    permanent_impact: float  # gamma: g(v) = gamma*v, price units per size
    volatility: float        # sigma: price units per sqrt(time), same time unit as tau
    risk_aversion: float     # lambda >= 0; 0 = risk-neutral, reduces exactly to TWAP

    def __post_init__(self):
        if self.temporary_impact <= 0:
            raise ValueError(f"temporary_impact (eta) must be positive, got {self.temporary_impact}")
        if self.permanent_impact < 0:
            raise ValueError(f"permanent_impact (gamma) must be >= 0, got {self.permanent_impact}")
        if self.volatility < 0:
            raise ValueError(f"volatility (sigma) must be >= 0, got {self.volatility}")
        if self.risk_aversion < 0:
            raise ValueError(f"risk_aversion (lambda) must be >= 0, got {self.risk_aversion}")


_KAPPA_ZERO_TOL = 1e-12


def optimal_holdings_trajectory(
    total_quantity: float, n_slices: int, tau: float, params: AlmgrenChrissParams
) -> list[float]:
    """x_0..x_n: remaining (unexecuted) quantity at each interval boundary,
    x_0 = total_quantity, x_n = 0. `tau` is the interval length, in the
    same time unit as `params.volatility`'s sqrt(time) denominator.
    """
    total_horizon = n_slices * tau
    eta_tilde = params.temporary_impact - 0.5 * params.permanent_impact * tau
    if eta_tilde <= 0:
        raise ValueError(
            f"eta - 0.5*gamma*tau = {eta_tilde} must be positive for the model to be "
            f"well-posed (temporary impact net of half the permanent impact per interval); "
            f"reduce gamma, increase eta, or use more slices to shrink tau"
        )

    kappa_tilde_sq = (params.risk_aversion * params.volatility ** 2) / eta_tilde

    if kappa_tilde_sq == 0:
        kappa = 0.0
    else:
        kappa = math.acosh(1 + tau ** 2 * kappa_tilde_sq / 2) / tau

    if kappa < _KAPPA_ZERO_TOL:
        # risk-neutral limit: sinh(k*a)/sinh(k*b) -> a/b as k -> 0
        return [total_quantity * (1 - j / n_slices) for j in range(n_slices + 1)]

    sinh_kappa_T = math.sinh(kappa * total_horizon)
    return [
        total_quantity * math.sinh(kappa * (total_horizon - j * tau)) / sinh_kappa_T
        for j in range(n_slices + 1)
    ]


class AlmgrenChrissAlgorithm(ExecutionAlgorithm):
    def __init__(self, n_slices: int, params: AlmgrenChrissParams):
        if n_slices < 1:
            raise ValueError(f"n_slices must be >= 1, got {n_slices}")
        self.n_slices = n_slices
        self.params = params

    def slice(self, parent: ParentOrder) -> list[ChildOrder]:
        duration_seconds = (parent.end_time - parent.start_time).total_seconds()
        tau = duration_seconds / self.n_slices

        holdings = optimal_holdings_trajectory(parent.quantity, self.n_slices, tau, self.params)

        return [
            ChildOrder(
                timestamp=parent.start_time + timedelta(seconds=tau * (j - 1)),
                quantity=holdings[j - 1] - holdings[j],
                side=parent.side,
            )
            for j in range(1, self.n_slices + 1)
        ]


def sensitivity_variants(params: AlmgrenChrissParams, pct: float = 0.2) -> dict:
    """One-at-a-time +/-pct perturbation of the two calibrated impact
    coefficients (eta, gamma), isolating which one the resulting
    trajectory/cost is more sensitive to -- volatility and risk_aversion
    are left fixed since they aren't what gets calibrated here."""
    return {
        "base": params,
        "eta_low": replace(params, temporary_impact=params.temporary_impact * (1 - pct)),
        "eta_high": replace(params, temporary_impact=params.temporary_impact * (1 + pct)),
        "gamma_low": replace(params, permanent_impact=params.permanent_impact * (1 - pct)),
        "gamma_high": replace(params, permanent_impact=params.permanent_impact * (1 + pct)),
    }
