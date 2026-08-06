"""Adapter functions between the Pydantic request models and this
project's existing business logic. Every function here composes
already-tested code from backtest/, algos/, venues/, and rl/ -- nothing
statistical or execution-related is reimplemented here, only translated
to/from plain dicts for the API layer. Each raises `ValueError` on bad
input (missing file, missing required calibration args, too little real
data) -- `backend/main.py` turns those into HTTP 400s.
"""

import os
from collections import Counter
from dataclasses import asdict
from datetime import timedelta

import pandas as pd

from algos.almgren_chriss import AlmgrenChrissAlgorithm
from algos.impact_calibration import build_empirical_params, compare_calibrations, literature_coefficients
from algos.twap import TWAPAlgorithm
from algos.vwap import VWAPAlgorithm
from backtest.algorithm import NaiveMarketOrderAlgorithm
from backtest.book_history import BookHistoryReader
from backtest.experiment import is_robust, run_bootstrap_experiment, window_regime_labels
from backtest.fill_model import FillModel
from backtest.order import ParentOrder
from backtest.scenarios import build_algorithm_scenarios
from backtest.simulator import OrderSlicingSimulator
from data.volume_profile import build_volume_profile
from rl.diagnostics import diagnose_training_run
from rl.episodes import enumerate_episode_windows
from venues.cross_venue_validation import compare_rankings_across_venues, rank_scenarios
from venues.fees import VENUE_FEE_SCHEDULES
from venues.multi_venue_simulator import MultiVenueSimulator
from venues.router import BestEffectivePriceRouter, SingleVenueRouter


def _build_single_algorithm(book_history: BookHistoryReader, req):
    """Same construction logic as backtest/run_backtest.py's CLI (and,
    separately, venues/run_multi_venue_backtest.py's) -- kept as its own
    small adapter here rather than forced through
    backtest.scenarios.build_algorithm_scenarios, which is shaped for the
    bootstrap-experiment use case (bps-only callables) and would throw
    away the full result this single-backtest endpoint needs to return.
    """
    algorithm = req.algorithm
    if algorithm == "twap":
        return TWAPAlgorithm(req.n_slices)

    if algorithm == "vwap":
        volume_csv = req.volume_csv or os.path.join(
            "data", "raw", "volume", f"{book_history.venue}_{book_history.symbol}_60m.csv"
        )
        if not os.path.exists(volume_csv):
            raise ValueError(f"no volume data at {volume_csv} -- pass volume_csv explicitly")
        volume_df = pd.read_csv(volume_csv, parse_dates=["open_time"])
        profile = build_volume_profile(volume_df, alpha=req.time_of_day_alpha)
        return VWAPAlgorithm(req.n_slices, profile.weights)

    if algorithm == "ac":
        missing = [
            name for name, val in [
                ("ac_calibration", req.ac_calibration),
                ("ac_volatility", req.ac_volatility),
                ("ac_risk_aversion", req.ac_risk_aversion),
                ("ac_permanent_to_temporary_ratio", req.ac_permanent_to_temporary_ratio),
            ] if val is None
        ]
        if missing:
            raise ValueError(f"algorithm=ac requires: {', '.join(missing)}")

        if req.ac_calibration == "literature":
            if req.ac_sqrt_law_coefficient is None or req.ac_reference_participation_rate is None:
                raise ValueError(
                    "ac_calibration=literature also requires ac_sqrt_law_coefficient "
                    "and ac_reference_participation_rate"
                )
            params = literature_coefficients(
                volatility=req.ac_volatility, risk_aversion=req.ac_risk_aversion,
                sqrt_law_coefficient=req.ac_sqrt_law_coefficient,
                reference_participation_rate=req.ac_reference_participation_rate,
                permanent_to_temporary_ratio=req.ac_permanent_to_temporary_ratio,
            )
        elif req.ac_calibration == "empirical":
            if req.ac_empirical_order_sizes is None:
                raise ValueError("ac_calibration=empirical also requires ac_empirical_order_sizes")
            order_sizes = [float(s) for s in req.ac_empirical_order_sizes.split(",")]
            params, _ = build_empirical_params(
                book_history, order_sizes, req.side,
                volatility=req.ac_volatility, risk_aversion=req.ac_risk_aversion,
                permanent_to_temporary_ratio=req.ac_permanent_to_temporary_ratio,
            )
        else:
            raise ValueError(f"ac_calibration must be 'literature' or 'empirical', got {req.ac_calibration!r}")
        return AlmgrenChrissAlgorithm(req.n_slices, params)

    return NaiveMarketOrderAlgorithm()


def _run_single_backtest(req):
    """Shared setup for run_backtest and run_backtest_trajectory -- both
    need the same parent order + algorithm + simulator run, just expose
    different levels of detail from the same BacktestResult."""
    book_history = BookHistoryReader(req.book_history_path)
    start_time = book_history.start_time + timedelta(seconds=req.start_offset_seconds)
    end_time = start_time + timedelta(seconds=req.duration_seconds)
    parent = ParentOrder(
        venue=book_history.venue, symbol=book_history.symbol, side=req.side,
        quantity=req.quantity, start_time=start_time, end_time=end_time,
    )

    fill_model = FillModel(req.temporary_impact_coef, req.permanent_impact_coef)
    algorithm = _build_single_algorithm(book_history, req)
    simulator = OrderSlicingSimulator(book_history, fill_model)
    result = simulator.run(parent, algorithm)
    return parent, result


def run_backtest(req) -> dict:
    parent, result = _run_single_backtest(req)
    s = result.shortfall

    return {
        "venue": parent.venue, "symbol": parent.symbol, "side": parent.side, "quantity": parent.quantity,
        "algorithm": req.algorithm,
        "arrival_price": result.arrival_price, "end_price": result.end_price,
        "n_child_orders": len(result.child_orders), "n_fills": len(result.fills),
        "executed_quantity": s.executed_quantity, "unfilled_quantity": s.unfilled_quantity,
        "executed_cost": s.executed_cost, "opportunity_cost": s.opportunity_cost,
        "total_cost": s.total_cost, "total_cost_bps": s.total_cost_bps,
    }


def run_backtest_trajectory(req) -> dict:
    """Remaining-inventory trajectory over time -- what the frontend's
    execution-trajectory plot needs, which the aggregate `run_backtest`
    response doesn't expose. Each `Fill.timestamp` equals its child
    order's own timestamp (`backtest/fill_model.py`), so fills are
    grouped back to the child order that produced them by matching on
    that timestamp -- no change needed to BacktestResult itself.
    """
    parent, result = _run_single_backtest(req)

    fills_by_timestamp = {}
    for fill in result.fills:
        fills_by_timestamp.setdefault(fill.timestamp, []).append(fill)

    remaining = parent.quantity
    points = [{"timestamp": parent.start_time.isoformat(), "remaining_quantity": remaining}]
    for child in result.child_orders:
        executed_here = sum(f.quantity for f in fills_by_timestamp.get(child.timestamp, []))
        remaining -= executed_here
        points.append({"timestamp": child.timestamp.isoformat(), "remaining_quantity": remaining})

    return {
        "venue": parent.venue, "algorithm": req.algorithm, "quantity": parent.quantity,
        "points": points,
    }


def run_experiment(req) -> list:
    book_history = BookHistoryReader(req.book_history_path)
    windows = enumerate_episode_windows(book_history, req.episode_duration_seconds, req.stride_seconds)
    if len(windows) < 2:
        raise ValueError(f"only {len(windows)} window(s) available -- need at least 2 to bootstrap")

    window_regimes = None
    if req.regimes_csv:
        if not os.path.exists(req.regimes_csv):
            raise ValueError(f"no regimes CSV at {req.regimes_csv}")
        regimes_df = pd.read_csv(req.regimes_csv, parse_dates=["open_time"])
        window_regimes = window_regime_labels(windows, regimes_df)

    fill_model = FillModel(req.temporary_impact_coef, req.permanent_impact_coef)
    scenarios = build_algorithm_scenarios(
        book_history, fill_model, req.side, req.quantity, req.n_slices,
        volume_csv=req.volume_csv, time_of_day_alpha=req.time_of_day_alpha,
        ac_volatility=req.ac_volatility, ac_risk_aversion=req.ac_risk_aversion,
        ac_permanent_to_temporary_ratio=req.ac_permanent_to_temporary_ratio,
        ac_sqrt_law_coefficient=req.ac_sqrt_law_coefficient,
        ac_reference_participation_rate=req.ac_reference_participation_rate,
        ac_empirical_order_sizes=req.ac_empirical_order_sizes,
        quiet=True,
    )

    results = run_bootstrap_experiment(
        windows, scenarios, window_regimes=window_regimes,
        n_resamples=req.n_resamples, confidence_level=req.confidence_level, seed=req.seed,
    )
    return [
        {
            "scenario": r.scenario, "regime": r.regime, "n_samples": r.bootstrap.n_samples,
            "mean_bps": r.bootstrap.point_estimate, "ci_low": r.bootstrap.ci_low,
            "ci_high": r.bootstrap.ci_high, "robust": is_robust(r),
        }
        for r in results
    ]


def compare_calibration(req) -> dict:
    book_history = BookHistoryReader(req.book_history_path)
    lit_params = literature_coefficients(
        volatility=req.ac_volatility, risk_aversion=req.ac_risk_aversion,
        sqrt_law_coefficient=req.ac_sqrt_law_coefficient,
        reference_participation_rate=req.ac_reference_participation_rate,
        permanent_to_temporary_ratio=req.ac_permanent_to_temporary_ratio,
    )
    order_sizes = [float(s) for s in req.ac_empirical_order_sizes.split(",")]
    emp_params, estimate = build_empirical_params(
        book_history, order_sizes, req.side,
        volatility=req.ac_volatility, risk_aversion=req.ac_risk_aversion,
        permanent_to_temporary_ratio=req.ac_permanent_to_temporary_ratio,
    )
    comparison = compare_calibrations(lit_params, emp_params)
    return {
        "venue": book_history.venue, "symbol": book_history.symbol,
        **comparison,
        "empirical_n_samples": estimate.n_samples,
        "empirical_r_squared": estimate.r_squared,
    }


def get_fee_schedules() -> list:
    return [
        {"venue": fs.venue, "maker_fee_bps": fs.maker_fee_bps, "taker_fee_bps": fs.taker_fee_bps, "source": fs.source}
        for fs in VENUE_FEE_SCHEDULES.values()
    ]


def cross_venue_validate(req) -> dict:
    fill_model = FillModel(req.temporary_impact_coef, req.permanent_impact_coef)
    paths = {
        "binance": req.binance_book_history_path,
        "coinbase": req.coinbase_book_history_path,
        "kraken": req.kraken_book_history_path,
    }

    per_venue_results = {}
    for venue, path in paths.items():
        book_history = BookHistoryReader(path)
        windows = enumerate_episode_windows(book_history, req.episode_duration_seconds, req.stride_seconds)
        if len(windows) < 2:
            continue

        window_regimes = None
        regimes_csv = os.path.join("data", "raw", "regimes", f"{venue}_regimes.csv")
        if os.path.exists(regimes_csv):
            regimes_df = pd.read_csv(regimes_csv, parse_dates=["open_time"])
            window_regimes = window_regime_labels(windows, regimes_df)

        scenarios = build_algorithm_scenarios(
            book_history, fill_model, req.side, req.quantity, req.n_slices, quiet=True
        )
        if len(scenarios) < 2:
            continue

        per_venue_results[venue] = run_bootstrap_experiment(
            windows, scenarios, window_regimes=window_regimes,
            n_resamples=req.n_resamples, confidence_level=req.confidence_level, seed=req.seed,
        )

    if len(per_venue_results) < 2:
        raise ValueError(f"only {len(per_venue_results)} venue(s) produced usable results -- need at least 2")

    rankings = {}
    for venue, results in per_venue_results.items():
        try:
            rankings[venue] = rank_scenarios(results, venue, regime=req.regime)
        except ValueError:
            continue
    if len(rankings) < 2:
        raise ValueError("fewer than 2 venues have a rankable comparison for this regime")

    report = compare_rankings_across_venues(rankings)
    return {
        "regime": report.regime,
        "rankings": {
            venue: {"ranking": ranking.ranking, "means": ranking.means, "robust": ranking.robust}
            for venue, ranking in rankings.items()
        },
        "common_scenarios": report.common_scenarios,
        "consistent": report.consistent,
        "common_ranking": report.common_ranking,
        "divergences": report.divergences,
    }


def get_rl_diagnostics(req) -> dict:
    if not os.path.exists(req.rewards_csv):
        raise ValueError(f"no rewards CSV at {req.rewards_csv}")
    result = diagnose_training_run(req.rewards_csv, window_fraction=req.window_fraction)
    return asdict(result)


def run_venue_routing_comparison(req) -> dict:
    """Step 10's routing comparison (venues.run_multi_venue_backtest),
    exposed as a service: the same parent order and algorithm run once
    against always-Binance/always-Coinbase/always-Kraken and
    best-effective-price routing, on real books for all three venues at
    once. A single real window per strategy (not bootstrapped) -- matches
    the CLI's own behavior exactly, see venues/README.md.
    """
    book_histories = {
        "binance": BookHistoryReader(req.binance_book_history_path),
        "coinbase": BookHistoryReader(req.coinbase_book_history_path),
        "kraken": BookHistoryReader(req.kraken_book_history_path),
    }
    if req.reference_venue not in book_histories:
        raise ValueError(f"reference_venue must be one of {list(book_histories)}, got {req.reference_venue!r}")

    reference_history = book_histories[req.reference_venue]
    start_time = reference_history.start_time + timedelta(seconds=req.start_offset_seconds)
    end_time = start_time + timedelta(seconds=req.duration_seconds)
    parent = ParentOrder(
        venue=req.reference_venue, symbol=reference_history.symbol, side=req.side,
        quantity=req.quantity, start_time=start_time, end_time=end_time,
    )

    fill_model = FillModel(req.temporary_impact_coef, req.permanent_impact_coef)
    algorithm = _build_single_algorithm(reference_history, req)

    routers = {f"always_{venue}": SingleVenueRouter(venue) for venue in book_histories}
    routers["best_price"] = BestEffectivePriceRouter()

    strategies = []
    for name, router in routers.items():
        simulator = MultiVenueSimulator(book_histories, VENUE_FEE_SCHEDULES, fill_model, router)
        result = simulator.run(parent, algorithm)
        routing_counts = dict(Counter(venue for _, venue in result.routing_decisions))
        strategies.append({
            "strategy": name,
            "total_cost_bps": result.shortfall.total_cost_bps,
            "executed_quantity": result.shortfall.executed_quantity,
            "routing_counts": routing_counts,
        })

    naive_strategies = [s for s in strategies if s["strategy"] != "best_price"]
    best_single_venue = min(naive_strategies, key=lambda s: s["total_cost_bps"])["strategy"]
    best_price_cost = next(s["total_cost_bps"] for s in strategies if s["strategy"] == "best_price")
    best_single_cost = next(s["total_cost_bps"] for s in strategies if s["strategy"] == best_single_venue)

    return {
        "reference_venue": req.reference_venue,
        "algorithm": req.algorithm,
        "strategies": strategies,
        "best_single_venue": best_single_venue,
        "smart_routing_improves": best_price_cost < best_single_cost,
    }
