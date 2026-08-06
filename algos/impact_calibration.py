"""Two calibration sources for Almgren-Chriss's linear impact coefficients
(eta, gamma), compared directly -- this is Step 7's core deliverable.

## Literature calibration: a disclosed gap, not a silent guess

The two standard citable sources for equities-derived linear impact
coefficients are Almgren & Chriss's own 2000 paper (which includes a
worked numerical example) and Almgren, Thum, Hauptmann & Li (2005)
"Direct Estimation of Equity Market Impact" (which fits eta/gamma-style
constants to real Citigroup order data). Both are only available to this
project as PDFs, and this environment has no PDF-to-text extraction tool
(no `pdftotext`/poppler, no `pypdf`/PyPDF2/PyMuPDF installed, and fetching
each PDF returned only its compressed internal stream structure, not
readable text) -- two independent attempts to pull the papers' exact
fitted digits did not succeed.

Rather than fabricate specific decimal coefficients this project cannot
verify, `literature_coefficients()` below uses the "square-root law"
functional form instead: cost ~ Y * sigma * sqrt(participation_rate).
This is the one claim from this literature that's safe to state without
pulling an exact fitted number: independent studies across different
markets and periods converge on Y being order-1 (roughly 0.5-1.5), not a
single precisely-sourced constant -- and it's the same functional form
already flagged in data/README.md as validated directly on Bitcoin
metaorders (Donier & Bonart, 2015), which is part of why it's the
reasonable choice here specifically. `sqrt_law_coefficient` (Y) has no
default: pass whatever value you can source, or 1.0 as the explicit
"textbook order-of-magnitude" convention -- not this project's own
finding, and not a substitute for the real fitted numbers if you have
access to either paper.

Since Almgren-Chriss needs *linear* impact (h(v) = eta*v) but the
square-root law is a power law, `literature_coefficients` converts one to
the other by matching costs at one reference participation rate:
eta * p_ref = Y * sigma * sqrt(p_ref)  =>  eta = Y * sigma / sqrt(p_ref).
This reference-point matching is itself a modeling choice, made visible
here rather than buried in a constant.

## Empirical calibration: real, but temporary-impact only

`estimate_empirical_temporary_impact()` regresses real book-walk slippage
(via backtest.fill_model with impact coefficients forced to zero, i.e.
pure real-liquidity arithmetic) against participation rate, across many
real recorded snapshots and candidate order sizes -- genuinely
asset-class-native, no literature dependency.

It cannot estimate *permanent* impact, and this is a real limitation, not
an oversight: observing permanent impact requires seeing real subsequent
price drift attributable to an actual trade of known size, which needs
real trade prints. This project's data pipeline (Steps 1-2) records order
book depth, not trade executions -- that data doesn't exist here. So the
"empirical" calibration set below still falls back to the same
`permanent_to_temporary_ratio` placeholder used in the literature set for
gamma. Only eta is genuinely empirical.
"""

import math
from dataclasses import dataclass

import pandas as pd

from algos.almgren_chriss import AlmgrenChrissParams
from backtest.book_history import BookHistoryReader
from backtest.fill_model import FillModel
from backtest.order import ChildOrder

REGIME_LABELS = ("calm", "normal", "volatile")


@dataclass
class EmpiricalImpactEstimate:
    temporary_impact: float  # eta_hat, fitted via OLS through the origin
    n_samples: int
    participation_rates: list
    slippage_fractions: list

    @property
    def r_squared(self) -> float:
        """R^2 for a no-intercept regression: 1 - SSres/SStot (SStot uses
        sum(y^2), since there's no mean to subtract without an intercept)."""
        if not self.participation_rates:
            return float("nan")
        predicted = [self.temporary_impact * p for p in self.participation_rates]
        ss_res = sum((y - yhat) ** 2 for y, yhat in zip(self.slippage_fractions, predicted))
        ss_tot = sum(y ** 2 for y in self.slippage_fractions)
        return 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def _collect_impact_samples(book_history: BookHistoryReader, indices, order_sizes, side: str):
    side_sign = 1 if side == "buy" else -1
    book_side = "ask" if side == "buy" else "bid"
    fill_model = FillModel(temporary_impact_coef=0.0, permanent_impact_coef=0.0)

    participation_rates, slippage_fractions = [], []
    for idx in indices:
        book = book_history.book_at_index(idx)
        arrival_mid = book.mid_price()
        if arrival_mid is None:
            continue
        levels = book.top_levels(book_side, n=len(book.asks if side == "buy" else book.bids))
        total_visible = sum(qty for _, qty in levels)
        if total_visible <= 0:
            continue

        for size in order_sizes:
            run = fill_model.new_run()
            child = ChildOrder(timestamp=book.last_update_time, quantity=size, side=side)
            result = run.execute(child, book)
            filled_qty = sum(f.quantity for f in result.fills)
            if filled_qty <= 0:
                continue
            avg_price = sum(f.price * f.quantity for f in result.fills) / filled_qty
            participation_rates.append(size / total_visible)
            slippage_fractions.append((avg_price - arrival_mid) / arrival_mid * side_sign)

    return participation_rates, slippage_fractions


def _fit_through_origin(participation_rates, slippage_fractions) -> float:
    denom = sum(p * p for p in participation_rates)
    if denom <= 0:
        return 0.0
    return sum(p * s for p, s in zip(participation_rates, slippage_fractions)) / denom


def estimate_empirical_temporary_impact(
    book_history: BookHistoryReader, order_sizes: list, side: str = "buy"
) -> EmpiricalImpactEstimate:
    rates, slippages = _collect_impact_samples(book_history, range(len(book_history)), order_sizes, side)
    if not rates:
        raise ValueError("no usable (book, order size) samples -- book history may be empty or too thin")
    return EmpiricalImpactEstimate(
        temporary_impact=_fit_through_origin(rates, slippages),
        n_samples=len(rates), participation_rates=rates, slippage_fractions=slippages,
    )


def estimate_empirical_temporary_impact_per_regime(
    book_history: BookHistoryReader, regimes_df: pd.DataFrame, order_sizes: list, side: str = "buy"
) -> dict:
    """`regimes_df` is data/analyze_regimes.py's output (columns open_time,
    regime), typically hourly. Each real book snapshot is matched to the
    most recent regime label at or before it (merge_asof, backward), then
    the same regression runs within each regime bucket separately."""
    regimes_df = regimes_df.sort_values("open_time")
    book_times = pd.DataFrame({"timestamp": book_history.timestamps})
    merged = pd.merge_asof(
        book_times, regimes_df[["open_time", "regime"]],
        left_on="timestamp", right_on="open_time", direction="backward",
    )
    regime_by_index = merged["regime"].tolist()

    results = {}
    for label in REGIME_LABELS:
        indices = [i for i, r in enumerate(regime_by_index) if r == label]
        if not indices:
            continue
        rates, slippages = _collect_impact_samples(book_history, indices, order_sizes, side)
        if not rates:
            continue
        results[label] = EmpiricalImpactEstimate(
            temporary_impact=_fit_through_origin(rates, slippages),
            n_samples=len(rates), participation_rates=rates, slippage_fractions=slippages,
        )
    return results


def literature_coefficients(
    volatility: float,
    risk_aversion: float,
    sqrt_law_coefficient: float,
    reference_participation_rate: float,
    permanent_to_temporary_ratio: float,
) -> AlmgrenChrissParams:
    """See module docstring for the full disclosure on why this is a
    stated square-root-law convention, not a verified fitted literature
    coefficient. No defaults: every judgment call here is a conscious,
    visible choice in the calling code, not a silently-picked one."""
    if reference_participation_rate <= 0:
        raise ValueError("reference_participation_rate must be positive")
    temporary_impact = sqrt_law_coefficient * volatility / math.sqrt(reference_participation_rate)
    return AlmgrenChrissParams(
        temporary_impact=temporary_impact,
        permanent_impact=permanent_to_temporary_ratio * temporary_impact,
        volatility=volatility,
        risk_aversion=risk_aversion,
    )


def build_empirical_params(
    book_history: BookHistoryReader,
    order_sizes: list,
    side: str,
    volatility: float,
    risk_aversion: float,
    permanent_to_temporary_ratio: float,
) -> tuple:
    """Returns (AlmgrenChrissParams, EmpiricalImpactEstimate) -- the estimate
    is kept alongside the params so callers/tests can inspect sample size
    and fit quality, not just the fitted eta."""
    estimate = estimate_empirical_temporary_impact(book_history, order_sizes, side)
    params = AlmgrenChrissParams(
        temporary_impact=estimate.temporary_impact,
        permanent_impact=permanent_to_temporary_ratio * estimate.temporary_impact,
        volatility=volatility,
        risk_aversion=risk_aversion,
    )
    return params, estimate


def compare_calibrations(literature: AlmgrenChrissParams, empirical: AlmgrenChrissParams) -> dict:
    def ratio(numerator, denominator):
        if denominator == 0:
            return float("inf") if numerator != 0 else float("nan")
        return numerator / denominator

    return {
        "temporary_impact_literature": literature.temporary_impact,
        "temporary_impact_empirical": empirical.temporary_impact,
        "temporary_impact_ratio": ratio(empirical.temporary_impact, literature.temporary_impact),
        "permanent_impact_literature": literature.permanent_impact,
        "permanent_impact_empirical": empirical.permanent_impact,
        "permanent_impact_ratio": ratio(empirical.permanent_impact, literature.permanent_impact),
    }
