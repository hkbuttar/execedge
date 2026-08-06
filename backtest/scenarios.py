"""Builds the standard naive/twap/vwap/ac_literature/ac_empirical
scenario set against a single venue's real recorded book history --
shared by `backtest.run_experiment` (one venue) and
`venues.cross_venue_validation` (the same comparison, repeated
independently per venue). Kept separate from `backtest/experiment.py`
(which stays generic -- a "scenario" there is just any callable) so that
module doesn't have to depend on every algorithm/calibration import.
"""

import os

import pandas as pd

from algos.almgren_chriss import AlmgrenChrissAlgorithm
from algos.impact_calibration import build_empirical_params, literature_coefficients
from algos.twap import TWAPAlgorithm
from algos.vwap import VWAPAlgorithm
from backtest.algorithm import NaiveMarketOrderAlgorithm
from backtest.book_history import BookHistoryReader
from backtest.fill_model import FillModel
from backtest.order import ParentOrder
from backtest.simulator import OrderSlicingSimulator
from data.volume_profile import build_volume_profile


def make_scenario(simulator, algorithm, side, quantity, venue, symbol):
    def run(window):
        parent = ParentOrder(
            venue=venue, symbol=symbol, side=side, quantity=quantity,
            start_time=window.start_time, end_time=window.end_time,
        )
        return simulator.run(parent, algorithm).shortfall.total_cost_bps

    return run


def build_algorithm_scenarios(
    book_history: BookHistoryReader,
    fill_model: FillModel,
    side: str,
    quantity: float,
    n_slices: int,
    volume_csv: str = None,
    time_of_day_alpha: float = 0.05,
    ac_volatility: float = None,
    ac_risk_aversion: float = None,
    ac_permanent_to_temporary_ratio: float = None,
    ac_sqrt_law_coefficient: float = None,
    ac_reference_participation_rate: float = None,
    ac_empirical_order_sizes: str = None,
    quiet: bool = False,
) -> dict:
    """Returns {scenario_name: callable(window) -> total_cost_bps}.
    `naive`/`twap` are always included; `vwap` is included if real volume
    data is found (default path or `volume_csv`); `ac_literature`/
    `ac_empirical` are included only if their respective calibration
    inputs are given -- silently absent scenarios are reported via
    print() (suppress with `quiet=True`), not raised as errors, since a
    caller running this across several venues shouldn't have one venue's
    missing volume file abort the whole comparison.
    """

    def log(msg):
        if not quiet:
            print(msg)

    simulator = OrderSlicingSimulator(book_history, fill_model)
    venue, symbol = book_history.venue, book_history.symbol

    scenarios = {
        "naive": make_scenario(simulator, NaiveMarketOrderAlgorithm(), side, quantity, venue, symbol),
        "twap": make_scenario(simulator, TWAPAlgorithm(n_slices), side, quantity, venue, symbol),
    }

    resolved_volume_csv = volume_csv or os.path.join(
        "data", "raw", "volume", f"{venue}_{symbol}_60m.csv"
    )
    if os.path.exists(resolved_volume_csv):
        volume_df = pd.read_csv(resolved_volume_csv, parse_dates=["open_time"])
        profile = build_volume_profile(volume_df, alpha=time_of_day_alpha)
        scenarios["vwap"] = make_scenario(
            simulator, VWAPAlgorithm(n_slices, profile.weights), side, quantity, venue, symbol
        )
    else:
        log(f"[{venue}] (skipping vwap: no volume data at {resolved_volume_csv})")

    ac_base_args_given = (
        ac_volatility is not None and ac_risk_aversion is not None
        and ac_permanent_to_temporary_ratio is not None
    )
    if ac_base_args_given:
        if ac_sqrt_law_coefficient is not None and ac_reference_participation_rate is not None:
            lit_params = literature_coefficients(
                volatility=ac_volatility, risk_aversion=ac_risk_aversion,
                sqrt_law_coefficient=ac_sqrt_law_coefficient,
                reference_participation_rate=ac_reference_participation_rate,
                permanent_to_temporary_ratio=ac_permanent_to_temporary_ratio,
            )
            scenarios["ac_literature"] = make_scenario(
                simulator, AlmgrenChrissAlgorithm(n_slices, lit_params), side, quantity, venue, symbol
            )
        if ac_empirical_order_sizes is not None:
            order_sizes = [float(s) for s in ac_empirical_order_sizes.split(",")]
            emp_params, _ = build_empirical_params(
                book_history, order_sizes, side,
                volatility=ac_volatility, risk_aversion=ac_risk_aversion,
                permanent_to_temporary_ratio=ac_permanent_to_temporary_ratio,
            )
            scenarios["ac_empirical"] = make_scenario(
                simulator, AlmgrenChrissAlgorithm(n_slices, emp_params), side, quantity, venue, symbol
            )
    else:
        log(
            f"[{venue}] (skipping ac_literature/ac_empirical: --ac-volatility/--ac-risk-aversion/"
            f"--ac-permanent-to-temporary-ratio not all given)"
        )

    return scenarios
