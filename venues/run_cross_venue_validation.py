"""Run the same algorithm comparison independently on each of Binance,
Coinbase, and Kraken's own real recorded book history, then check
whether the ranking of algorithms (does Almgren-Chriss beat VWAP, does
VWAP beat TWAP) holds consistently across venues, or diverges.

Each venue is judged entirely on its own real data -- no cross-venue data
leakage: separate book history, separate real volume/regime data,
separate bootstrap confidence intervals per venue. This is deliberately
NOT the same thing as `venues.run_multi_venue_backtest` (which routes a
single execution across venues); this asks whether the *conclusion* --
which algorithm wins -- replicates when you look at three genuinely
different real order books, the closest thing this crypto-only project
has to a cross-asset-class robustness check.

    python3 -m lob.run_reconstruction --venues binance coinbase kraken --record-depth-levels 50 --minutes 60
    python3 -m data.fetch_volume --days 30 --interval 60
    python3 -m data.analyze_regimes --interval 60 --vol-window 24
    python3 -m venues.run_cross_venue_validation \\
        --binance-book-history lob/raw/binance_book_snapshots.jsonl \\
        --coinbase-book-history lob/raw/coinbase_book_snapshots.jsonl \\
        --kraken-book-history lob/raw/kraken_book_snapshots.jsonl \\
        --side buy --quantity 1.0 --n-slices 5 \\
        --episode-duration-seconds 60 --stride-seconds 60 \\
        --temporary-impact-coef 0.0 --permanent-impact-coef 0.0
"""

import argparse
import os

import pandas as pd

from backtest.experiment import run_bootstrap_experiment, window_regime_labels
from backtest.book_history import open_book_history
from backtest.fill_model import FillModel
from backtest.scenarios import build_algorithm_scenarios
from rl.episodes import enumerate_episode_windows
from venues.cross_venue_validation import compare_rankings_across_venues, rank_scenarios

VENUES = ("binance", "coinbase", "kraken")


def run_one_venue(venue, book_history_path, fill_model, args):
    book_history = open_book_history(book_history_path)
    windows = enumerate_episode_windows(book_history, args.episode_duration_seconds, args.stride_seconds)
    if len(windows) < 2:
        print(f"[{venue}] only {len(windows)} window(s) available -- skipping this venue")
        return None
    print(f"[{venue}] {len(windows)} real historical windows enumerated")

    window_regimes = None
    regimes_csv = os.path.join("data", "raw", "regimes", f"{venue}_regimes.csv")
    if os.path.exists(regimes_csv):
        regimes_df = pd.read_csv(regimes_csv, parse_dates=["open_time"])
        window_regimes = window_regime_labels(windows, regimes_df)
    else:
        print(f"[{venue}] no regimes CSV at {regimes_csv} -- reporting 'all' only for this venue")

    scenarios = build_algorithm_scenarios(
        book_history, fill_model, args.side, args.quantity, args.n_slices,
        time_of_day_alpha=args.time_of_day_alpha,
        ac_volatility=args.ac_volatility, ac_risk_aversion=args.ac_risk_aversion,
        ac_permanent_to_temporary_ratio=args.ac_permanent_to_temporary_ratio,
        ac_sqrt_law_coefficient=args.ac_sqrt_law_coefficient,
        ac_reference_participation_rate=args.ac_reference_participation_rate,
        ac_empirical_order_sizes=args.ac_empirical_order_sizes,
    )
    if len(scenarios) < 2:
        print(f"[{venue}] fewer than 2 algorithm scenarios available -- skipping this venue")
        return None

    return run_bootstrap_experiment(
        windows, scenarios, window_regimes=window_regimes,
        n_resamples=args.n_resamples, confidence_level=args.confidence_level, seed=args.seed,
    )


def print_ranking(ranking):
    print(f"\n[{ranking.venue}] regime={ranking.regime} ranking (best to worst):")
    for scenario in ranking.ranking:
        robust = "robust" if ranking.robust[scenario] else "fragile"
        print(f"    {scenario:<16} {ranking.means[scenario]:>8.2f} bps  ({robust})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binance-book-history", required=True)
    parser.add_argument("--coinbase-book-history", required=True)
    parser.add_argument("--kraken-book-history", required=True)
    parser.add_argument("--side", choices=["buy", "sell"], required=True)
    parser.add_argument("--quantity", type=float, required=True)
    parser.add_argument("--n-slices", type=int, default=10)
    parser.add_argument("--episode-duration-seconds", type=float, required=True)
    parser.add_argument("--stride-seconds", type=float, required=True)
    parser.add_argument("--temporary-impact-coef", type=float, required=True)
    parser.add_argument("--permanent-impact-coef", type=float, required=True)
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
    parser.add_argument(
        "--regime", default="all",
        help="which regime label to rank/compare across venues (default 'all', "
        "the pooled-across-all-real-windows comparison)",
    )

    args = parser.parse_args()

    fill_model = FillModel(args.temporary_impact_coef, args.permanent_impact_coef)
    book_history_paths = {
        "binance": args.binance_book_history,
        "coinbase": args.coinbase_book_history,
        "kraken": args.kraken_book_history,
    }

    per_venue_results = {}
    for venue in VENUES:
        results = run_one_venue(venue, book_history_paths[venue], fill_model, args)
        if results is not None:
            per_venue_results[venue] = results

    if len(per_venue_results) < 2:
        raise SystemExit(
            f"only {len(per_venue_results)} venue(s) produced usable results -- "
            f"need at least 2 to cross-venue-validate"
        )

    rankings = {}
    for venue, results in per_venue_results.items():
        try:
            rankings[venue] = rank_scenarios(results, venue, regime=args.regime)
        except ValueError as exc:
            print(f"[{venue}] {exc} -- excluding this venue from the comparison")
    for ranking in rankings.values():
        print_ranking(ranking)

    if len(rankings) < 2:
        raise SystemExit("fewer than 2 venues have a rankable comparison -- nothing to cross-validate")

    report = compare_rankings_across_venues(rankings)
    print(f"\ncommon scenarios across all venues: {report.common_scenarios}")
    if report.consistent:
        print(
            f"RANKING IS CONSISTENT across {', '.join(rankings)} for regime={report.regime!r}: "
            f"{report.common_ranking}"
        )
    else:
        print(f"RANKING DIVERGES across venues for regime={report.regime!r}:")
        for divergence in report.divergences:
            print(f"  - {divergence}")


if __name__ == "__main__":
    main()
