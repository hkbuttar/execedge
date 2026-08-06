"""Run the same parent order and algorithm across Binance, Coinbase, and
Kraken's real recorded books, comparing four routing strategies in one
shot: always-Binance, always-Coinbase, always-Kraken (the three "naive,
no real routing decision" baselines), and best-effective-price (real
quote + real taker fee, decided per child order at its own real
timestamp) -- "does smarter routing meaningfully reduce cost," answered
directly, honestly, either way.

Needs a recorded book history for all three venues:

    python3 -m lob.run_reconstruction --venues binance coinbase kraken --record-depth-levels 50 --minutes 30
    python3 -m venues.run_multi_venue_backtest \\
        --binance-book-history lob/raw/binance_book_snapshots.jsonl \\
        --coinbase-book-history lob/raw/coinbase_book_snapshots.jsonl \\
        --kraken-book-history lob/raw/kraken_book_snapshots.jsonl \\
        --side buy --quantity 1.0 --algorithm twap --n-slices 10 \\
        --start-offset-seconds 0 --duration-seconds 300 \\
        --temporary-impact-coef 0.0 --permanent-impact-coef 0.0

Any `backtest.algorithm.ExecutionAlgorithm` works here unmodified,
including the RL policy (`rl.policy_algorithm.TrainedPolicyAlgorithm`)
-- this CLI only wires up naive/twap/vwap/ac directly, but
`MultiVenueSimulator` itself doesn't know or care what kind of algorithm
object it's calling `.slice()` on. That's the point of routing being a
cross-cutting layer (see venues/README.md) rather than something baked
into each algorithm: RL decides *how much to trade when* using its own
venue's real signals, unmodified; this layer decides *where*
to actually execute using all three venues' real quotes and fees,
without RL needing to know routing exists.
"""

import argparse
import os
from collections import Counter
from datetime import timedelta

import pandas as pd

from algos.almgren_chriss import AlmgrenChrissAlgorithm
from algos.impact_calibration import build_empirical_params, literature_coefficients
from algos.twap import TWAPAlgorithm
from algos.vwap import VWAPAlgorithm
from backtest.algorithm import NaiveMarketOrderAlgorithm
from backtest.book_history import BookHistoryReader
from backtest.fill_model import FillModel
from backtest.order import ParentOrder
from data.volume_profile import build_volume_profile
from venues.fees import VENUE_FEE_SCHEDULES
from venues.multi_venue_simulator import MultiVenueSimulator
from venues.router import BestEffectivePriceRouter, SingleVenueRouter

VENUES = ("binance", "coinbase", "kraken")


def build_algorithm(args, reference_venue: str, reference_history: BookHistoryReader):
    if args.algorithm == "twap":
        return TWAPAlgorithm(args.n_slices)

    if args.algorithm == "vwap":
        volume_csv = args.volume_csv or os.path.join(
            "data", "raw", "volume",
            f"{reference_venue}_{reference_history.symbol}_{args.volume_interval}m.csv",
        )
        if not os.path.exists(volume_csv):
            raise SystemExit(f"no volume data at {volume_csv} -- run `python3 -m data.fetch_volume` first")
        volume_df = pd.read_csv(volume_csv, parse_dates=["open_time"])
        profile = build_volume_profile(volume_df, alpha=args.time_of_day_alpha)
        shape = "flat (no significant time-of-day effect)" if profile.is_flat else "curved (real hour-of-day pattern)"
        print(f"VWAP profile ({reference_venue}): {shape}, p={profile.tod_test['p_value']:.4f}")
        return VWAPAlgorithm(args.n_slices, profile.weights)

    if args.algorithm == "ac":
        missing = [
            name for name, val in [
                ("--ac-calibration", args.ac_calibration),
                ("--ac-volatility", args.ac_volatility),
                ("--ac-risk-aversion", args.ac_risk_aversion),
                ("--ac-permanent-to-temporary-ratio", args.ac_permanent_to_temporary_ratio),
            ] if val is None
        ]
        if missing:
            raise SystemExit(f"--algorithm ac requires: {', '.join(missing)}")

        if args.ac_calibration == "literature":
            if args.ac_sqrt_law_coefficient is None or args.ac_reference_participation_rate is None:
                raise SystemExit(
                    "--ac-calibration literature also requires --ac-sqrt-law-coefficient "
                    "and --ac-reference-participation-rate"
                )
            params = literature_coefficients(
                volatility=args.ac_volatility, risk_aversion=args.ac_risk_aversion,
                sqrt_law_coefficient=args.ac_sqrt_law_coefficient,
                reference_participation_rate=args.ac_reference_participation_rate,
                permanent_to_temporary_ratio=args.ac_permanent_to_temporary_ratio,
            )
        else:
            if args.ac_empirical_order_sizes is None:
                raise SystemExit("--ac-calibration empirical also requires --ac-empirical-order-sizes")
            order_sizes = [float(s) for s in args.ac_empirical_order_sizes.split(",")]
            # Empirical impact is estimated from the reference venue's own
            # real book only, applied uniformly even to child orders that
            # end up routed elsewhere -- a disclosed simplification, see
            # venues/README.md.
            params, _ = build_empirical_params(
                reference_history, order_sizes, args.side,
                volatility=args.ac_volatility, risk_aversion=args.ac_risk_aversion,
                permanent_to_temporary_ratio=args.ac_permanent_to_temporary_ratio,
            )
        return AlmgrenChrissAlgorithm(args.n_slices, params)

    return NaiveMarketOrderAlgorithm()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binance-book-history", required=True)
    parser.add_argument("--coinbase-book-history", required=True)
    parser.add_argument("--kraken-book-history", required=True)
    parser.add_argument("--reference-venue", choices=VENUES, default="binance")
    parser.add_argument("--side", choices=["buy", "sell"], required=True)
    parser.add_argument("--quantity", type=float, required=True)
    parser.add_argument("--start-offset-seconds", type=float, default=0)
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--algorithm", choices=["naive", "twap", "vwap", "ac"], default="twap")
    parser.add_argument("--n-slices", type=int, default=10)
    parser.add_argument("--volume-csv", default=None)
    parser.add_argument("--volume-interval", type=int, default=60)
    parser.add_argument("--time-of-day-alpha", type=float, default=0.05)
    parser.add_argument("--temporary-impact-coef", type=float, required=True)
    parser.add_argument("--permanent-impact-coef", type=float, required=True)
    parser.add_argument("--ac-calibration", choices=["literature", "empirical"], default=None)
    parser.add_argument("--ac-volatility", type=float, default=None)
    parser.add_argument("--ac-risk-aversion", type=float, default=None)
    parser.add_argument("--ac-permanent-to-temporary-ratio", type=float, default=None)
    parser.add_argument("--ac-sqrt-law-coefficient", type=float, default=None)
    parser.add_argument("--ac-reference-participation-rate", type=float, default=None)
    parser.add_argument("--ac-empirical-order-sizes", default=None)
    args = parser.parse_args()

    book_histories = {
        "binance": BookHistoryReader(args.binance_book_history),
        "coinbase": BookHistoryReader(args.coinbase_book_history),
        "kraken": BookHistoryReader(args.kraken_book_history),
    }
    reference_history = book_histories[args.reference_venue]
    start_time = reference_history.start_time + timedelta(seconds=args.start_offset_seconds)
    end_time = start_time + timedelta(seconds=args.duration_seconds)

    parent = ParentOrder(
        venue=args.reference_venue, symbol=reference_history.symbol, side=args.side,
        quantity=args.quantity, start_time=start_time, end_time=end_time,
    )

    fill_model = FillModel(
        temporary_impact_coef=args.temporary_impact_coef,
        permanent_impact_coef=args.permanent_impact_coef,
    )
    algorithm = build_algorithm(args, args.reference_venue, reference_history)

    routers = {
        "always_binance": SingleVenueRouter("binance"),
        "always_coinbase": SingleVenueRouter("coinbase"),
        "always_kraken": SingleVenueRouter("kraken"),
        "best_price": BestEffectivePriceRouter(),
    }

    print(f"{parent.side} {parent.quantity} {parent.symbol}, algorithm={args.algorithm}, "
          f"reference venue={args.reference_venue} (arrival/end price benchmark)")
    print(f"fee schedules (taker, base tier): "
          + ", ".join(f"{v}={VENUE_FEE_SCHEDULES[v].taker_fee_bps:.1f}bps" for v in VENUES))

    results = {}
    for name, router in routers.items():
        simulator = MultiVenueSimulator(book_histories, VENUE_FEE_SCHEDULES, fill_model, router)
        result = simulator.run(parent, algorithm)
        results[name] = result
        venue_counts = dict(Counter(venue for _, venue in result.routing_decisions))
        print(
            f"  {name}: shortfall={result.shortfall.total_cost_bps:.2f} bps  "
            f"executed={result.shortfall.executed_quantity:.4f}  routing={venue_counts}"
        )

    naive_names = ("always_binance", "always_coinbase", "always_kraken")
    best_single_venue = min(naive_names, key=lambda n: results[n].shortfall.total_cost_bps)
    improvement_bps = (
        results[best_single_venue].shortfall.total_cost_bps - results["best_price"].shortfall.total_cost_bps
    )

    print(f"\nbest single-venue choice: {best_single_venue} "
          f"({results[best_single_venue].shortfall.total_cost_bps:.2f} bps)")
    print(f"smart (best-price) routing: {results['best_price'].shortfall.total_cost_bps:.2f} bps")
    if improvement_bps > 0:
        print(f"smart routing improves cost by {improvement_bps:.2f} bps vs. the best single venue")
    else:
        print(f"smart routing does NOT improve cost here ({-improvement_bps:.2f} bps worse than "
              f"just always using {best_single_venue}) -- reported as-is")


if __name__ == "__main__":
    main()
