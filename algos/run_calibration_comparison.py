"""Dedicated literature-vs-empirical Almgren-Chriss comparison: builds
both calibrations from the same real book history and side, and prints
the magnitude of divergence directly -- the results-writeup requirement
this project treats as a genuine finding in its own right (see
algos/README.md), not just an internal calibration detail.

    python3 -m algos.run_calibration_comparison \\
        --book-history lob/raw/binance_book_snapshots.jsonl \\
        --side buy \\
        --ac-volatility 0.001 --ac-risk-aversion 0.1 \\
        --ac-permanent-to-temporary-ratio 0.01 \\
        --ac-sqrt-law-coefficient 1.0 --ac-reference-participation-rate 0.1 \\
        --ac-empirical-order-sizes 0.05,0.1,0.5,1.0

No numbers here are fabricated placeholders: the literature side is the
same disclosed square-root-law convention documented in
algos/README.md's "disclosed gap in the literature source" section (not
a verified fitted coefficient -- swap in real published numbers if you
have access to them), and the empirical side is a real regression against
whatever book history you point this at.
"""

import argparse

from algos.impact_calibration import build_empirical_params, compare_calibrations, literature_coefficients
from backtest.book_history import BookHistoryReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-history", required=True)
    parser.add_argument("--side", choices=["buy", "sell"], required=True)
    parser.add_argument("--ac-volatility", type=float, required=True)
    parser.add_argument("--ac-risk-aversion", type=float, required=True)
    parser.add_argument("--ac-permanent-to-temporary-ratio", type=float, required=True)
    parser.add_argument("--ac-sqrt-law-coefficient", type=float, required=True)
    parser.add_argument("--ac-reference-participation-rate", type=float, required=True)
    parser.add_argument("--ac-empirical-order-sizes", required=True)
    args = parser.parse_args()

    book_history = BookHistoryReader(args.book_history)

    lit_params = literature_coefficients(
        volatility=args.ac_volatility, risk_aversion=args.ac_risk_aversion,
        sqrt_law_coefficient=args.ac_sqrt_law_coefficient,
        reference_participation_rate=args.ac_reference_participation_rate,
        permanent_to_temporary_ratio=args.ac_permanent_to_temporary_ratio,
    )

    order_sizes = [float(s) for s in args.ac_empirical_order_sizes.split(",")]
    emp_params, estimate = build_empirical_params(
        book_history, order_sizes, args.side,
        volatility=args.ac_volatility, risk_aversion=args.ac_risk_aversion,
        permanent_to_temporary_ratio=args.ac_permanent_to_temporary_ratio,
    )

    comparison = compare_calibrations(lit_params, emp_params)

    print(f"venue: {book_history.venue}  symbol: {book_history.symbol}  side: {args.side}")
    print(f"empirical fit: n_samples={estimate.n_samples}  r_squared={estimate.r_squared:.4f}")
    print()
    print(f"{'':<20} {'literature':>14} {'empirical':>14} {'ratio (emp/lit)':>18}")
    print(
        f"{'temporary_impact':<20} {comparison['temporary_impact_literature']:>14.6g} "
        f"{comparison['temporary_impact_empirical']:>14.6g} {comparison['temporary_impact_ratio']:>18.3f}"
    )
    print(
        f"{'permanent_impact':<20} {comparison['permanent_impact_literature']:>14.6g} "
        f"{comparison['permanent_impact_empirical']:>14.6g} {comparison['permanent_impact_ratio']:>18.3f}"
    )

    ratio = comparison["temporary_impact_ratio"]
    print()
    if ratio > 3 or ratio < 1 / 3:
        print(
            f"literature and empirical calibration diverge substantially "
            f"({ratio:.2f}x on temporary impact) -- given the literature side is an "
            f"equities-motivated convention (see algos/README.md) and the empirical "
            f"side reflects this venue's own real crypto liquidity, that divergence "
            f"is itself a disclosed, reportable finding, not an error."
        )
    else:
        print(
            f"literature and empirical calibration are roughly consistent "
            f"({ratio:.2f}x on temporary impact) for this venue/window -- also worth "
            f"reporting as-is, not a result to expect universally."
        )


if __name__ == "__main__":
    main()
