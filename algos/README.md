# Execution algorithms

Concrete strategies against `backtest.algorithm.ExecutionAlgorithm` (see
`backtest/README.md` for the harness they run inside). This is
distinguished from `backtest.algorithm.NaiveMarketOrderAlgorithm`, which
is a harness-exercise baseline, not a real strategy.

## TWAP (`twap.py`) — the control

Equal-size slices at regular time intervals: `parent.quantity / n_slices`
per child, spaced `duration / n_slices` apart, starting at
`parent.start_time`. It ignores everything -- the real volume profile,
current book depth, any impact model -- by design. Every other algorithm
in this project (VWAP, Almgren-Chriss, RL) is benchmarked against it;
outperforming TWAP means demonstrating a real edge from whatever
information that algorithm uses and TWAP doesn't.

```
python3 -m backtest.run_backtest \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy --quantity 1.0 --algorithm twap --n-slices 10 \
    --start-offset-seconds 0 --duration-seconds 300 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0
```

`tests/test_algorithm_comparison.py` demonstrates concretely why slicing
matters: against a synthetic thin book, a single-shot order walks five
price levels for an average fill of 102.0, while TWAP's smaller slices
each fit inside the best level, averaging 100.0. That test also documents
a real caveat worth internalizing before reading too much into any
TWAP-vs-naive comparison against a *live* recorded history: the simulator
replays independently-recorded real snapshots and does not deplete a
level for a later child order just because an earlier one consumed it at
a different timestamp. Against a real recording the book moves between
snapshots for real reasons, so this isn't "free" liquidity in practice --
but it's worth being aware the mechanism exists.

## VWAP (`vwap.py`) — built on the real volume curve

Same regular-interval slicing as TWAP (n_slices equal-duration buckets
across the window), but each bucket's size is weighted by its hour-of-
day's real historical volume share (`data/volume_profile.py`) instead of
1/n_slices. The weights come from `data.time_of_day`'s ANOVA:

- **No significant time-of-day effect found** → the profile is flat
  (every hour weighted 1/24) → VWAP's sizing is mathematically identical
  to TWAP. Not a fallback bug: there's nothing in the real data to shape
  the curve around, so it shouldn't invent one.
- **Significant effect found** → the profile uses the real empirical
  per-hour volume shares, so slices scheduled in historically high-volume
  hours get proportionally larger child orders.

This is "let the data decide" enforced in code rather than assumed:
equities' well-known open/close volume spike is never hardcoded anywhere
in this path.

One resolution limit worth knowing: the profile is hourly. A parent
order whose entire window sits inside one hour gets flat weighting
regardless of the profile — there's no finer real signal to differentiate
slices within that hour (`tests/test_vwap.py::test_within_single_hour_window_is_effectively_flat`
demonstrates this directly).

```
python3 -m data.fetch_volume --days 30 --interval 60
python3 -m backtest.run_backtest \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy --quantity 1.0 --algorithm vwap --n-slices 10 \
    --start-offset-seconds 0 --duration-seconds 300 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0
```

(`--volume-csv` defaults to `data/raw/volume/{venue}_{symbol}_{volume-interval}m.csv`,
matching `data.fetch_volume`'s default output naming.)

## Almgren-Chriss (`almgren_chriss.py`, `impact_calibration.py`)

Citation: Almgren, R., Chriss, N. (2000). "Optimal Execution of Portfolio
Transactions." *Journal of Risk*, 3, 5-39. Closed-form optimal
remaining-holdings trajectory:

```
x_j = X * sinh(kappa*(T - t_j)) / sinh(kappa*T)
kappa = arccosh(1 + tau^2 * kappa_tilde^2 / 2) / tau
kappa_tilde^2 = risk_aversion * sigma^2 / (eta - 0.5*gamma*tau)
```

These formulas were cross-checked against two independent sources before
implementing (not taken purely from memory), given how central this
equation is to the whole comparison. `tests/test_almgren_chriss.py`
verifies the two properties that matter most:

- **`risk_aversion = 0` produces an *exactly* identical child order
  schedule to `TWAPAlgorithm`** (same quantities, same timestamps) —
  TWAP is the risk-neutral special case of Almgren-Chriss, not just a
  separately-simpler strategy. This is checked to floating-point
  precision, not approximately.
- **`risk_aversion > 0` front-loads execution** (earlier slices larger
  than later ones), trading more market impact for less exposure to
  price risk over the remaining horizon — the model's whole point.

The model has a real well-posedness constraint worth knowing before you
hit it: `eta - 0.5*gamma*tau` must be positive, or there's no real
solution. If you get a `ValueError` about this, either use more slices
(smaller `tau`) or reduce `permanent_to_temporary_ratio` — this is the
model correctly rejecting an inconsistent combination of your own inputs,
not a bug.

### Dual calibration — and a disclosed gap in the literature source

**Literature calibration** is supposed to use published, equities-derived
impact coefficients. In practice: the two standard
citable sources — Almgren-Chriss's own 2000 paper's worked numerical
example, and Almgren/Thum/Hauptmann/Li (2005) "Direct Estimation of
Equity Market Impact," which fits coefficients to real Citigroup order
data — are both only available to this project as PDFs, and this
environment has no working PDF-to-text extraction (no poppler/pdftotext,
no pypdf/PyMuPDF, and fetching each PDF returned only compressed internal
stream structure rather than readable text). Two independent attempts to
pull the papers' exact fitted digits did not succeed.

Rather than fabricate specific-looking decimal coefficients that can't be
verified, `literature_coefficients()` uses the square-root-law functional
form instead (`cost ~ Y * sigma * sqrt(participation_rate)`) — the one
claim from this literature safe to state without an exact citation:
independent studies across markets converge on `Y` being order-1
(roughly 0.5-1.5), not one precisely-sourced number, and it's the same
form already flagged in `data/README.md` as validated directly on Bitcoin
metaorders (Donier & Bonart, 2015). Every input to this function —
`sqrt_law_coefficient`, `reference_participation_rate`,
`permanent_to_temporary_ratio` — has **no default**, same discipline as
`backtest/fill_model.py`'s impact coefficients: pick 1.0 as the explicit
"textbook order-of-magnitude" convention if you have nothing better, but
know that's what it is. **If you have access to either paper's actual
fitted numbers, replace this function's convention with them** — that's
a strict improvement over what's here now.

**Empirical calibration** (`estimate_empirical_temporary_impact`) is
genuinely asset-class-native: it regresses real book-walk slippage
(via `backtest.fill_model` with impact forced to zero — pure arithmetic
against real recorded depth) against participation rate, across many
real snapshots and candidate order sizes, fitting `eta` by ordinary least
squares through the origin (consistent with linear `h(v) = eta*v`).
`tests/test_impact_calibration.py` proves this recovers a known-planted
linear impact law to `1e-9` relative precision against a constructed
book, and separately confirms the plumbing (`estimate_empirical_temporary_impact_per_regime`)
correctly splits samples by the calm/normal/volatile labels via a
timestamp join (`pandas.merge_asof`) against `data/analyze_regimes.py`'s
output.

**It cannot estimate permanent impact**, and this is a real limitation,
not an oversight: observing permanent impact needs real subsequent price
drift attributable to an actual trade of known size — that needs real
trade prints. This project's data pipeline records order book *depth*,
not trade executions, so that data doesn't exist here. The "empirical"
calibration set's `gamma` still falls back to the same
`permanent_to_temporary_ratio` placeholder as the literature set — only
`eta` is genuinely empirical.

**Comparing the two** (`compare_calibrations`, exposed as a dedicated
report by `algos.run_calibration_comparison`) is itself one of the
intended findings here: run both, look at the ratio.

```
python3 -m algos.run_calibration_comparison \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy \
    --ac-volatility 0.001 --ac-risk-aversion 0.1 --ac-permanent-to-temporary-ratio 0.01 \
    --ac-sqrt-law-coefficient 1.0 --ac-reference-participation-rate 0.1 \
    --ac-empirical-order-sizes 0.05,0.1,0.5,1.0,2.0
```

Given the fill model's book-walk `eta` reflects this project's own
recorded crypto liquidity and the literature convention is an
equities-motivated order-of-magnitude placeholder, a large divergence
wouldn't be surprising — but that's exactly the kind of honest, disclosed
result this project is set up to report rather than paper over. See
`RESULTS.md` for an actual run of this against real recorded data (they
landed within 25% of each other there — roughly consistent, not the
large divergence that would also have been a legitimate finding).

**Sensitivity analysis** (`algos.almgren_chriss.sensitivity_variants`,
±20%) perturbs `eta` and `gamma` one at a time (not jointly), isolating
which of the two calibrated coefficients the resulting trajectory is more
sensitive to.

**Cross-calibration sanity check** (`tests/test_ac_calibration_sanity.py`):
literature and empirical calibration can genuinely diverge in their raw
eta/gamma values (that's a disclosed finding above, not a bug) — but
regardless of how much they diverge, neither should ever produce an
insane trajectory. This test verifies both calibrations, run against the
same real synthetic order book, produce non-negative quantities summing
to the parent order's quantity, front-load execution by a comparable
order of magnitude (within 100x of each other, a sanity bound not a
precision claim), and both still hit the exact risk-neutral-reduces-to-
TWAP special case regardless of how different their coefficients are.

```
# literature calibration
python3 -m backtest.run_backtest \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy --quantity 1.0 --algorithm ac --n-slices 10 \
    --start-offset-seconds 0 --duration-seconds 300 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0 \
    --ac-calibration literature --ac-volatility 0.02 --ac-risk-aversion 0.3 \
    --ac-permanent-to-temporary-ratio 0.01 --ac-sqrt-law-coefficient 1.0 \
    --ac-reference-participation-rate 0.1

# empirical calibration -- eta estimated from the same recorded book history
python3 -m backtest.run_backtest \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy --quantity 1.0 --algorithm ac --n-slices 10 \
    --start-offset-seconds 0 --duration-seconds 300 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0 \
    --ac-calibration empirical --ac-volatility 0.02 --ac-risk-aversion 0.3 \
    --ac-permanent-to-temporary-ratio 0.01 --ac-empirical-order-sizes 0.1,0.5,1.0,2.0,5.0
```

## Also compared against

- An RL execution policy (`rl/`) — see `rl/README.md`. It plugs into the
  same `backtest.algorithm.ExecutionAlgorithm` interface as everything
  above via `rl.policy_algorithm.TrainedPolicyAlgorithm`, so it's
  benchmarked against TWAP/VWAP/AC through the identical harness rather
  than a separate evaluation path.
