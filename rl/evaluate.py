"""Evaluate a trained RL execution policy against TWAP and Almgren-Chriss
on the exact same held-out test episodes (rl.train's walk-forward split),
using the same backtest.simulator/backtest.metrics.implementation_shortfall
every other algorithm in this project is scored with -- an apples-to-
apples comparison, not a separate RL-only evaluation loop.

Reports honestly: if the RL policy underperforms Almgren-Chriss, that's
exactly what gets printed, consistent with how this project has handled
every other disclosed limitation so far (see data/README.md, algos/README.md).

    python3 -m rl.evaluate \\
        --book-history lob/raw/binance_book_snapshots.jsonl \\
        --model rl/raw/dqn_execution_policy.zip \\
        --side buy --quantity 1.0 --n-steps 10 \\
        --ac-calibration literature --ac-volatility 0.001 --ac-risk-aversion 0.1 \\
        --ac-permanent-to-temporary-ratio 0.01 --ac-sqrt-law-coefficient 1.0 \\
        --ac-reference-participation-rate 0.1
"""

import argparse
import json
import os
from datetime import datetime

from stable_baselines3 import DQN

from algos.almgren_chriss import AlmgrenChrissAlgorithm
from algos.impact_calibration import build_empirical_params, literature_coefficients
from algos.twap import TWAPAlgorithm
from backtest.book_history import BookHistoryReader
from backtest.fill_model import FillModel
from backtest.order import ParentOrder
from backtest.simulator import OrderSlicingSimulator
from rl.policy_algorithm import TrainedPolicyAlgorithm


def load_test_windows(model_path: str):
    path = os.path.splitext(model_path)[0] + "_test_windows.json"
    if not os.path.exists(path):
        raise SystemExit(f"no test-windows file at {path} -- run rl.train first, it writes this alongside the model")
    with open(path) as f:
        rows = json.load(f)
    return [(datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])) for r in rows]


def build_ac_params(args, book_history):
    if args.ac_calibration == "literature":
        if args.ac_sqrt_law_coefficient is None or args.ac_reference_participation_rate is None:
            raise SystemExit(
                "--ac-calibration literature also requires --ac-sqrt-law-coefficient "
                "and --ac-reference-participation-rate"
            )
        return literature_coefficients(
            volatility=args.ac_volatility,
            risk_aversion=args.ac_risk_aversion,
            sqrt_law_coefficient=args.ac_sqrt_law_coefficient,
            reference_participation_rate=args.ac_reference_participation_rate,
            permanent_to_temporary_ratio=args.ac_permanent_to_temporary_ratio,
        )
    if args.ac_empirical_order_sizes is None:
        raise SystemExit("--ac-calibration empirical also requires --ac-empirical-order-sizes")
    order_sizes = [float(s) for s in args.ac_empirical_order_sizes.split(",")]
    params, _ = build_empirical_params(
        book_history, order_sizes, args.side,
        volatility=args.ac_volatility, risk_aversion=args.ac_risk_aversion,
        permanent_to_temporary_ratio=args.ac_permanent_to_temporary_ratio,
    )
    return params


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-history", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--side", choices=["buy", "sell"], required=True)
    parser.add_argument("--quantity", type=float, required=True)
    parser.add_argument("--n-steps", type=int, default=10)
    parser.add_argument("--ac-calibration", choices=["literature", "empirical"], required=True)
    parser.add_argument("--ac-volatility", type=float, required=True)
    parser.add_argument("--ac-risk-aversion", type=float, required=True)
    parser.add_argument("--ac-permanent-to-temporary-ratio", type=float, required=True)
    parser.add_argument("--ac-sqrt-law-coefficient", type=float, default=None)
    parser.add_argument("--ac-reference-participation-rate", type=float, default=None)
    parser.add_argument("--ac-empirical-order-sizes", default=None)
    args = parser.parse_args()

    book_history = BookHistoryReader(args.book_history)
    test_windows = load_test_windows(args.model)
    if not test_windows:
        raise SystemExit("test-windows file is empty")

    model = DQN.load(args.model)
    ac_params = build_ac_params(args, book_history)

    algorithms = {
        "twap": TWAPAlgorithm(args.n_steps),
        "almgren_chriss": AlmgrenChrissAlgorithm(args.n_steps, ac_params),
        "rl_policy": TrainedPolicyAlgorithm(model, book_history, args.n_steps),
    }

    fill_model = FillModel(temporary_impact_coef=0.0, permanent_impact_coef=0.0)
    simulator = OrderSlicingSimulator(book_history, fill_model)

    results = {name: [] for name in algorithms}
    for start, end in test_windows:
        parent = ParentOrder(
            venue=book_history.venue, symbol=book_history.symbol, side=args.side,
            quantity=args.quantity, start_time=start, end_time=end,
        )
        for name, algorithm in algorithms.items():
            result = simulator.run(parent, algorithm)
            results[name].append(result.shortfall.total_cost_bps)

    print(f"{len(test_windows)} held-out test episodes (never seen during training)")
    means = {}
    for name, values in results.items():
        means[name] = sum(values) / len(values)
        print(f"  {name}: mean shortfall = {means[name]:.2f} bps (n={len(values)})")

    if means["rl_policy"] > means["almgren_chriss"]:
        print(
            f"\nRL policy underperforms Almgren-Chriss on this test set "
            f"({means['rl_policy']:.2f} bps vs {means['almgren_chriss']:.2f} bps)."
        )
    else:
        print(
            f"\nRL policy outperforms Almgren-Chriss on this test set "
            f"({means['rl_policy']:.2f} bps vs {means['almgren_chriss']:.2f} bps)."
        )


if __name__ == "__main__":
    main()
