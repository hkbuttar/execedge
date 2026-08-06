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
behavior with no assumed impact; Step 7 is where literature/empirical
values for these get produced.

Algorithms available: `naive` (single-shot baseline, exercises the
harness only) and `twap` (Step 5's control -- equal slices at regular
intervals, pass --n-slices). VWAP/Almgren-Chriss (Steps 6-7) will add
more choices here.
"""

import argparse
from datetime import timedelta

from algos.twap import TWAPAlgorithm
from backtest.algorithm import NaiveMarketOrderAlgorithm
from backtest.book_history import BookHistoryReader
from backtest.fill_model import FillModel
from backtest.order import ParentOrder
from backtest.simulator import OrderSlicingSimulator

ALGORITHMS = {"naive": NaiveMarketOrderAlgorithm, "twap": TWAPAlgorithm}


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
    parser.add_argument("--n-slices", type=int, default=10, help="only used by --algorithm twap")
    parser.add_argument("--temporary-impact-coef", type=float, required=True)
    parser.add_argument("--permanent-impact-coef", type=float, required=True)
    args = parser.parse_args()

    book_history = BookHistoryReader(args.book_history)
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
    simulator = OrderSlicingSimulator(book_history, fill_model)
    algorithm = TWAPAlgorithm(args.n_slices) if args.algorithm == "twap" else NaiveMarketOrderAlgorithm()

    result = simulator.run(parent, algorithm)
    s = result.shortfall

    print(f"{parent.side} {parent.quantity} {parent.symbol} on {parent.venue}")
    print(f"arrival price: {result.arrival_price}  end price: {result.end_price}")
    print(f"child orders: {len(result.child_orders)}  fills: {len(result.fills)}")
    print(f"executed: {s.executed_quantity}  unfilled: {s.unfilled_quantity}")
    print(f"executed cost: {s.executed_cost:.4f}  opportunity cost: {s.opportunity_cost:.4f}")
    print(f"total shortfall: {s.total_cost:.4f} ({s.total_cost_bps:.2f} bps)")


if __name__ == "__main__":
    main()
