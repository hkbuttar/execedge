"""Run the order-slicing simulator against a real recorded book history.

Needs a book-snapshot file first (from lob/run_reconstruction.py run with
--record-depth-levels > 0):

    python3 -m lob.run_reconstruction --venues binance --record-depth-levels 50 --minutes 30
    python3 -m backtest.run_backtest \\
        --book-history lob/raw/binance_book_snapshots.jsonl \\
        --side buy --quantity 1.0 \\
        --start-offset-seconds 0 --duration-seconds 300 \\
        --temporary-impact-coef 0.0 --permanent-impact-coef 0.0

`--temporary-impact-coef`/`--permanent-impact-coef` have no default on
purpose (see backtest/fill_model.py) -- pass 0.0 to see pure book-walk
behavior with no assumed impact; the Almgren-Chriss module is where
literature/empirical values for these get produced.

Algorithms available: `naive` (single-shot baseline, exercises the
harness only), `twap` (the control -- equal slices at regular
intervals, pass --n-slices), `vwap` (slices proportional to a
real historical volume curve, needs --volume-csv from
`data.fetch_volume`'s output; falls back to a flat/TWAP-equivalent
profile if the time-of-day test found no real pattern for this
venue), and `ac` (Almgren-Chriss closed-form trajectory, pass
--ac-calibration literature|empirical; see algos/README.md for what each
means and the disclosed gap in the literature source).

The risk layer (risk/) is optional and off by default:
--participation-limit caps each child order against real volume
(risk/README.md on the proration caveat), and --kill-switch-max-vol /
--kill-switch-max-shortfall-bps halt all remaining child orders for the
rest of the run once tripped -- manual reset only, there's no
auto-resume.
"""

import argparse
import os
from datetime import timedelta

import pandas as pd

from algos.almgren_chriss import AlmgrenChrissAlgorithm
from algos.impact_calibration import build_empirical_params, literature_coefficients
from algos.twap import TWAPAlgorithm
from algos.vwap import VWAPAlgorithm
from backtest.algorithm import NaiveMarketOrderAlgorithm
from backtest.book_history import open_book_history
from backtest.fill_model import FillModel
from backtest.order import ParentOrder
from backtest.simulator import OrderSlicingSimulator
from data.volume_profile import build_volume_profile
from risk.kill_switch import KillSwitch
from risk.participation_limit import ParticipationLimiter
from risk.triggers import shortfall_trigger, volatility_trigger
from risk.volume_lookup import HistoricalVolumeLookup

ALGORITHMS = {
    "naive": NaiveMarketOrderAlgorithm,
    "twap": TWAPAlgorithm,
    "vwap": VWAPAlgorithm,
    "ac": AlmgrenChrissAlgorithm,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-history", required=True)
    parser.add_argument("--side", choices=["buy", "sell"], required=True)
    parser.add_argument("--quantity", type=float, required=True)
    parser.add_argument(
        "--start-offset-seconds", type=float, default=0,
        help="parent order start time, as seconds after the book history's first record",
    )
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--algorithm", choices=list(ALGORITHMS), default="naive")
    parser.add_argument("--n-slices", type=int, default=10, help="used by --algorithm twap/vwap/ac")
    parser.add_argument(
        "--volume-csv", default=None,
        help="data.fetch_volume output CSV, required for --algorithm vwap "
        "(default: data/raw/volume/{venue}_{symbol}_{volume-interval}m.csv)",
    )
    parser.add_argument("--volume-interval", type=int, default=60, help="must match the fetched CSV's bar size")
    parser.add_argument("--time-of-day-alpha", type=float, default=0.05)
    parser.add_argument("--temporary-impact-coef", type=float, required=True)
    parser.add_argument("--permanent-impact-coef", type=float, required=True)

    parser.add_argument("--ac-calibration", choices=["literature", "empirical"], default=None)
    parser.add_argument("--ac-volatility", type=float, default=None, help="sigma, price units per sqrt(second)")
    parser.add_argument("--ac-risk-aversion", type=float, default=None, help="lambda >= 0; 0 reduces exactly to TWAP")
    parser.add_argument("--ac-permanent-to-temporary-ratio", type=float, default=None)
    parser.add_argument(
        "--ac-sqrt-law-coefficient", type=float, default=None,
        help="literature calibration only -- see algos/README.md's disclosed-limitation note",
    )
    parser.add_argument("--ac-reference-participation-rate", type=float, default=None, help="literature calibration only")
    parser.add_argument(
        "--ac-empirical-order-sizes", default=None,
        help="empirical calibration only -- comma-separated sizes to sample, e.g. 0.1,0.5,1.0,2.0,5.0",
    )

    parser.add_argument(
        "--participation-limit", type=float, default=None,
        help="cap each child order at this fraction (0,1] of real historical volume in its window; off by default",
    )
    parser.add_argument(
        "--kill-switch-max-vol", type=float, default=None,
        help="halt all remaining child orders if realized volatility exceeds this",
    )
    parser.add_argument(
        "--kill-switch-max-shortfall-bps", type=float, default=None,
        help="halt all remaining child orders if cumulative shortfall exceeds this many bps",
    )
    args = parser.parse_args()

    book_history = open_book_history(args.book_history)
    start_time = book_history.start_time + timedelta(seconds=args.start_offset_seconds)
    end_time = start_time + timedelta(seconds=args.duration_seconds)

    parent = ParentOrder(
        venue=book_history.venue,
        symbol=book_history.symbol,
        side=args.side,
        quantity=args.quantity,
        start_time=start_time,
        end_time=end_time,
    )

    fill_model = FillModel(
        temporary_impact_coef=args.temporary_impact_coef,
        permanent_impact_coef=args.permanent_impact_coef,
    )

    participation_limiter = None
    if args.participation_limit is not None:
        volume_csv = args.volume_csv or os.path.join(
            "data", "raw", "volume", f"{book_history.venue}_{book_history.symbol}_{args.volume_interval}m.csv"
        )
        if not os.path.exists(volume_csv):
            raise SystemExit(
                f"--participation-limit needs real volume data at {volume_csv} -- "
                f"run `python3 -m data.fetch_volume` first, or pass --volume-csv explicitly"
            )
        volume_df = pd.read_csv(volume_csv, parse_dates=["open_time"])
        volume_lookup = HistoricalVolumeLookup(volume_df, bar_seconds=args.volume_interval * 60)
        participation_limiter = ParticipationLimiter(args.participation_limit, volume_lookup)
        print(f"participation limit: {args.participation_limit:.4%} of real volume per child order window")

    kill_switch = None
    kill_switch_triggers = []
    if args.kill_switch_max_vol is not None or args.kill_switch_max_shortfall_bps is not None:
        kill_switch = KillSwitch()
        if args.kill_switch_max_vol is not None:
            kill_switch_triggers.append(volatility_trigger(args.kill_switch_max_vol))
        if args.kill_switch_max_shortfall_bps is not None:
            kill_switch_triggers.append(shortfall_trigger(args.kill_switch_max_shortfall_bps))

    simulator = OrderSlicingSimulator(
        book_history, fill_model,
        participation_limiter=participation_limiter,
        kill_switch=kill_switch,
        kill_switch_triggers=kill_switch_triggers,
    )

    if args.algorithm == "twap":
        algorithm = TWAPAlgorithm(args.n_slices)
    elif args.algorithm == "vwap":
        volume_csv = args.volume_csv or os.path.join(
            "data", "raw", "volume", f"{book_history.venue}_{book_history.symbol}_{args.volume_interval}m.csv"
        )
        if not os.path.exists(volume_csv):
            raise SystemExit(
                f"no volume data at {volume_csv} -- run `python3 -m data.fetch_volume` first, "
                f"or pass --volume-csv explicitly"
            )
        volume_df = pd.read_csv(volume_csv, parse_dates=["open_time"])
        profile = build_volume_profile(volume_df, alpha=args.time_of_day_alpha)
        shape = "flat (no significant time-of-day effect)" if profile.is_flat else "curved (real hour-of-day pattern)"
        print(f"VWAP profile: {shape}, p={profile.tod_test['p_value']:.4f}")
        algorithm = VWAPAlgorithm(args.n_slices, profile.weights)
    elif args.algorithm == "ac":
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
                volatility=args.ac_volatility,
                risk_aversion=args.ac_risk_aversion,
                sqrt_law_coefficient=args.ac_sqrt_law_coefficient,
                reference_participation_rate=args.ac_reference_participation_rate,
                permanent_to_temporary_ratio=args.ac_permanent_to_temporary_ratio,
            )
            print(
                f"AC literature calibration: eta={params.temporary_impact:.6g} "
                f"gamma={params.permanent_impact:.6g} (see algos/README.md's disclosed-limitation note)"
            )
        else:
            if args.ac_empirical_order_sizes is None:
                raise SystemExit("--ac-calibration empirical also requires --ac-empirical-order-sizes")
            order_sizes = [float(s) for s in args.ac_empirical_order_sizes.split(",")]
            params, estimate = build_empirical_params(
                book_history, order_sizes, args.side,
                volatility=args.ac_volatility,
                risk_aversion=args.ac_risk_aversion,
                permanent_to_temporary_ratio=args.ac_permanent_to_temporary_ratio,
            )
            print(
                f"AC empirical calibration: eta={params.temporary_impact:.6g} "
                f"gamma={params.permanent_impact:.6g} (n_samples={estimate.n_samples}, "
                f"r_squared={estimate.r_squared:.4f}; gamma is still the placeholder ratio -- "
                f"see algos/README.md)"
            )
        algorithm = AlmgrenChrissAlgorithm(args.n_slices, params)
    else:
        algorithm = NaiveMarketOrderAlgorithm()

    result = simulator.run(parent, algorithm)
    s = result.shortfall

    if result.halted_at is not None and kill_switch is not None:
        print(f"KILL SWITCH TRIPPED at {result.halted_at}: {kill_switch.event.reason}")

    print(f"{parent.side} {parent.quantity} {parent.symbol} on {parent.venue}")
    print(f"arrival price: {result.arrival_price}  end price: {result.end_price}")
    print(f"child orders: {len(result.child_orders)}  fills: {len(result.fills)}")
    print(f"executed: {s.executed_quantity}  unfilled: {s.unfilled_quantity}")
    print(f"executed cost: {s.executed_cost:.4f}  opportunity cost: {s.opportunity_cost:.4f}")
    print(f"total shortfall: {s.total_cost:.4f} ({s.total_cost_bps:.2f} bps)")


if __name__ == "__main__":
    main()
