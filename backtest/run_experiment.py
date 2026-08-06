"""Run every algorithm (and, optionally, every venue-routing
strategy) across many real historical windows, stratified by the
regime labels, reporting implementation shortfall with bootstrap
confidence intervals.

Two separate comparisons, not one giant combinatorial grid -- nobody
could usefully read algorithm x regime x venue-routing x calibration all
at once, and most of those cells would have too few real windows to
bootstrap meaningfully given how much recorded history that would need
(see backtest/README.md):

  1. Algorithm comparison (single venue): naive, twap, vwap (if volume
     data available), ac_literature/ac_empirical (if AC params given) --
     covers "algorithm x regime x calibration-source".
  2. Venue-routing comparison (only if --binance/coinbase/kraken-book-history
     are all given): always-X per venue vs. best-effective-price, using
     TWAP as the fixed algorithm -- covers "venue-routing x regime".

    python3 -m lob.run_reconstruction --venues binance --record-depth-levels 50 --minutes 60
    python3 -m data.fetch_volume --days 30 --interval 60
    python3 -m data.analyze_regimes --interval 60 --vol-window 24
    python3 -m backtest.run_experiment \\
        --book-history lob/raw/binance_book_snapshots.jsonl \\
        --side buy --quantity 1.0 --n-slices 5 \\
        --episode-duration-seconds 60 --stride-seconds 60 \\
        --temporary-impact-coef 0.0 --permanent-impact-coef 0.0 \\
        --regimes-csv data/raw/regimes/binance_regimes.csv
"""

import argparse
import os

import pandas as pd

from algos.twap import TWAPAlgorithm
from backtest.book_history import open_book_history
from backtest.experiment import is_robust, run_bootstrap_experiment, window_regime_labels
from backtest.fill_model import FillModel
from backtest.order import ParentOrder
from backtest.scenarios import build_algorithm_scenarios
from rl.episodes import enumerate_episode_windows
from venues.fees import VENUE_FEE_SCHEDULES
from venues.multi_venue_simulator import MultiVenueSimulator
from venues.router import BestEffectivePriceRouter, SingleVenueRouter


def print_results_table(results, title):
    print(f"\n=== {title} ===")
    print(f"{'regime':<10} {'scenario':<16} {'n':>4} {'mean bps':>10} {'95% CI':>22} {'robust?':>8}")
    for r in sorted(results, key=lambda r: (r.regime, r.scenario)):
        b = r.bootstrap
        ci = f"[{b.ci_low:.2f}, {b.ci_high:.2f}]"
        robust = "yes" if is_robust(r) else "no"
        print(f"{r.regime:<10} {r.scenario:<16} {b.n_samples:>4} {b.point_estimate:>10.2f} {ci:>22} {robust:>8}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-history", required=True)
    parser.add_argument("--side", choices=["buy", "sell"], required=True)
    parser.add_argument("--quantity", type=float, required=True)
    parser.add_argument("--n-slices", type=int, default=10)
    parser.add_argument("--episode-duration-seconds", type=float, required=True)
    parser.add_argument("--stride-seconds", type=float, required=True)
    parser.add_argument("--temporary-impact-coef", type=float, required=True)
    parser.add_argument("--permanent-impact-coef", type=float, required=True)
    parser.add_argument(
        "--regimes-csv", default=None,
        help="data.analyze_regimes output; omit to skip regime stratification (report 'all' only)",
    )

    parser.add_argument("--volume-csv", default=None)
    parser.add_argument("--time-of-day-alpha", type=float, default=0.05)

    parser.add_argument("--ac-volatility", type=float, default=None)
    parser.add_argument("--ac-risk-aversion", type=float, default=None)
    parser.add_argument("--ac-permanent-to-temporary-ratio", type=float, default=None)
    parser.add_argument("--ac-sqrt-law-coefficient", type=float, default=None)
    parser.add_argument("--ac-reference-participation-rate", type=float, default=None)
    parser.add_argument("--ac-empirical-order-sizes", default=None)

    parser.add_argument("--n-resamples", type=int, default=2000)
    parser.add_argument("--confidence-level", type=float, default=0.95)
    parser.add_argument("--seed", type=int, default=None)

    parser.add_argument("--binance-book-history", default=None, help="enables the venue-routing comparison")
    parser.add_argument("--coinbase-book-history", default=None, help="enables the venue-routing comparison")
    parser.add_argument("--kraken-book-history", default=None, help="enables the venue-routing comparison")
    parser.add_argument(
        "--reference-venue", choices=["binance", "coinbase", "kraken"], default="binance",
        help="venue-routing comparison only: which venue's book anchors the shortfall benchmark",
    )

    args = parser.parse_args()

    book_history = open_book_history(args.book_history)
    windows = enumerate_episode_windows(book_history, args.episode_duration_seconds, args.stride_seconds)
    if len(windows) < 2:
        raise SystemExit(
            f"only {len(windows)} window(s) available -- need at least 2 to bootstrap; "
            f"record more history or shorten --episode-duration-seconds/--stride-seconds"
        )
    print(f"{len(windows)} real historical windows enumerated from {args.book_history}")

    window_regimes = None
    if args.regimes_csv:
        if not os.path.exists(args.regimes_csv):
            raise SystemExit(f"no regimes CSV at {args.regimes_csv} -- run `python3 -m data.analyze_regimes` first")
        regimes_df = pd.read_csv(args.regimes_csv, parse_dates=["open_time"])
        window_regimes = window_regime_labels(windows, regimes_df)

    fill_model = FillModel(args.temporary_impact_coef, args.permanent_impact_coef)

    # --- 1. algorithm comparison (single venue) ---
    algorithm_scenarios = build_algorithm_scenarios(
        book_history, fill_model, args.side, args.quantity, args.n_slices,
        volume_csv=args.volume_csv, time_of_day_alpha=args.time_of_day_alpha,
        ac_volatility=args.ac_volatility, ac_risk_aversion=args.ac_risk_aversion,
        ac_permanent_to_temporary_ratio=args.ac_permanent_to_temporary_ratio,
        ac_sqrt_law_coefficient=args.ac_sqrt_law_coefficient,
        ac_reference_participation_rate=args.ac_reference_participation_rate,
        ac_empirical_order_sizes=args.ac_empirical_order_sizes,
    )

    algorithm_results = run_bootstrap_experiment(
        windows, algorithm_scenarios, window_regimes=window_regimes,
        n_resamples=args.n_resamples, confidence_level=args.confidence_level, seed=args.seed,
    )
    print_results_table(algorithm_results, "Algorithm comparison (single venue)")

    # --- 2. venue-routing comparison (optional) ---
    if args.binance_book_history and args.coinbase_book_history and args.kraken_book_history:
        book_histories = {
            "binance": open_book_history(args.binance_book_history),
            "coinbase": open_book_history(args.coinbase_book_history),
            "kraken": open_book_history(args.kraken_book_history),
        }
        reference_venue = args.reference_venue
        reference_symbol = book_histories[reference_venue].symbol
        twap = TWAPAlgorithm(args.n_slices)
        routing_scenarios = {}

        for venue in book_histories:
            mv_sim = MultiVenueSimulator(book_histories, VENUE_FEE_SCHEDULES, fill_model, SingleVenueRouter(venue))
            routing_scenarios[f"always_{venue}"] = make_routing_scenario(
                mv_sim, twap, args.side, args.quantity, reference_venue, reference_symbol
            )

        best_price_sim = MultiVenueSimulator(
            book_histories, VENUE_FEE_SCHEDULES, fill_model, BestEffectivePriceRouter()
        )
        routing_scenarios["best_price"] = make_routing_scenario(
            best_price_sim, twap, args.side, args.quantity, reference_venue, reference_symbol
        )

        routing_results = run_bootstrap_experiment(
            windows, routing_scenarios, window_regimes=window_regimes,
            n_resamples=args.n_resamples, confidence_level=args.confidence_level, seed=args.seed,
        )
        print_results_table(routing_results, f"Venue-routing comparison (TWAP, reference venue={reference_venue})")
    else:
        print(
            "\n(skipping venue-routing comparison: --binance-book-history/--coinbase-book-history/"
            "--kraken-book-history not all given)"
        )


def make_routing_scenario(multi_venue_simulator, algorithm, side, quantity, reference_venue, reference_symbol):
    def run(window):
        parent = ParentOrder(
            venue=reference_venue, symbol=reference_symbol,
            side=side, quantity=quantity, start_time=window.start_time, end_time=window.end_time,
        )
        return multi_venue_simulator.run(parent, algorithm).shortfall.total_cost_bps

    return run


if __name__ == "__main__":
    main()
