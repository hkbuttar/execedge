# Results & honest comparison

The full comparison this project is built to produce: algorithm ×
regime × venue-routing × calibration-source × exchange on implementation
shortfall (with confidence intervals), plus a dedicated literature-vs-
empirical Almgren-Chriss divergence check, with robust-vs-fragile flagged
explicitly rather than left to eyeballing a table.

**What follows is a real run against real recorded data already in this
repo, not a template with invented numbers** — every figure below came
from actually executing the commands shown, against actual real-market
snapshots. But it's also honestly a small one: ~5 minutes of Binance
book history, no Coinbase/Kraken *book* recordings yet (only their volume
data). That's enough to prove the whole reporting pipeline produces real,
correctly-computed numbers end to end — it is **not** enough to draw a
confident final verdict from. Extending this to something conclusive
means running the same commands against much longer, multi-venue
recordings; the gaps below say exactly what's missing.

## Which tool produces which slice

| Slice of the full table | Tool |
|---|---|
| algorithm × regime × calibration-source (one exchange) | `backtest.run_experiment` |
| venue-routing × regime (one reference exchange, TWAP) | `backtest.run_experiment --binance/coinbase/kraken-book-history`, or `venues.run_multi_venue_backtest` for a single-window view |
| algorithm ranking consistency × exchange | `venues.run_cross_venue_validation` |
| literature vs. empirical Almgren-Chriss divergence | `algos.run_calibration_comparison` |
| RL vs. TWAP/Almgren-Chriss on held-out episodes | `rl.evaluate` |
| RL training diagnostics | `rl.diagnose` |

"Robust" throughout means `backtest.experiment.is_robust`'s stated
heuristic — a bootstrap CI narrower than half its own point estimate —
not a formal significance test. Treat any "fragile" row's conclusion,
including its sign, with real caution.

## 1. Algorithm × regime (Binance, real data)

```
python3 -m backtest.run_experiment \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy --quantity 1.0 --n-slices 5 \
    --episode-duration-seconds 30 --stride-seconds 30 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0 \
    --regimes-csv data/raw/regimes/binance_regimes.csv \
    --ac-volatility 0.001 --ac-risk-aversion 0.1 --ac-permanent-to-temporary-ratio 0.01 \
    --ac-sqrt-law-coefficient 1.0 --ac-reference-participation-rate 0.1 \
    --ac-empirical-order-sizes 0.05,0.1,0.5,1.0,2.0
```

| regime | scenario | n | mean bps | 95% CI | robust? |
|---|---|---|---|---|---|
| all | naive | 9 | 2.69 | [2.10, 3.30] | **yes** |
| all | twap | 9 | 2.21 | [1.48, 2.98] | no |
| all | vwap | 9 | 2.21 | [1.48, 2.98] | no |
| all | ac_literature | 9 | 2.21 | [1.48, 2.97] | no |
| all | ac_empirical | 9 | 2.21 | [1.48, 2.97] | no |

All 9 real windows in this recording happened to fall in the "calm"
regime label, so `calm` reproduces the `all` row exactly and `normal`/
`volatile` have zero windows — a direct consequence of the recording
only spanning 5 real minutes, not a finding about regime behavior.

**Honest reading**: naive (single-shot) is the one row with a robust CI,
and it's the worst performer — slicing an order at all clearly helps
here. But TWAP, VWAP, and both Almgren-Chriss calibrations land on
*exactly* the same mean (2.21 bps) with fragile, overlapping CIs. That's
consistent with two things already disclosed elsewhere in this project,
not a new surprise: VWAP degenerates to TWAP when Binance shows no
significant time-of-day effect (`data/README.md`), and with
`risk_aversion=0.1` this small, Almgren-Chriss's trajectory barely
diverges from TWAP's flat schedule (`algos/README.md`). This dataset is
too small (n=9) to say anything about whether they'd separate given more
real windows or a larger `risk_aversion` — that's a gap, not a
conclusion.

## 2. Literature vs. empirical Almgren-Chriss divergence (Binance, real data)

```
python3 -m algos.run_calibration_comparison \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy \
    --ac-volatility 0.001 --ac-risk-aversion 0.1 --ac-permanent-to-temporary-ratio 0.01 \
    --ac-sqrt-law-coefficient 1.0 --ac-reference-participation-rate 0.1 \
    --ac-empirical-order-sizes 0.05,0.1,0.5,1.0,2.0
```

| | literature | empirical | ratio (emp/lit) |
|---|---|---|---|
| temporary_impact | 0.00316 | 0.00238 | 0.75x |
| permanent_impact | 3.16e-05 | 2.38e-05 | 0.75x |

Empirical fit: n=1435 samples, r²=0.89 (a real regression against 1435
real book-walk observations from this recording, not a small sample).

**Honest reading**: these land within 25% of each other here — *roughly*
consistent, not the substantial divergence `algos/README.md` flags as
plausible. Two caveats worth stating before reading too much into that:
(1) the literature side is this project's own square-root-law
*convention* (`sqrt_law_coefficient=1.0`), not a verified fitted
published number (see `algos/README.md`'s disclosed gap) — a different
convention choice would shift this ratio directly; (2) one 5-minute
window on one venue is a single data point, not a validated result.
Worth re-running once real published coefficients are available, and
across more real windows.

## 3. RL vs. TWAP/Almgren-Chriss (Binance, real data)

From an actual `rl.evaluate` run against this same recording (3 held-out
test episodes, a model trained for 2000 timesteps — see `rl/README.md`
for why that's a smoke test, not a properly trained policy):

| scenario | mean bps |
|---|---|
| twap | 2.74 |
| almgren_chriss | 2.74 |
| rl_policy | 2.88 |

RL underperforms Almgren-Chriss here, reported as-is per `rl/README.md`'s
discipline. Given the training budget (2000 timesteps, 3 test episodes),
this says essentially nothing about whether RL *can* beat AC with
adequate training — it says a barely-trained policy on a few minutes of
split data doesn't beat a well-specified analytical baseline, which is
unsurprising.

## 4. RL training diagnostics (real training run)

```
python3 -m rl.diagnose --rewards-csv rl/raw/training_rewards.csv
```

```
400 completed episodes
reward: mean=-5.2728 std=17.8836 min=-51.6030 max=26.4050
early-window mean reward: -10.1317
late-window mean reward:  0.7241
reward improved from early to late training -- worth evaluating further
```

Real signal that training was doing *something* (reward trended up
across the run), consistent with it not yet being enough training to
beat Almgren-Chriss above.

## 5. Venue-routing and cross-venue validation — not yet run

This repo currently has real *book* history for Binance only;
Coinbase and Kraken have real *volume* data but no recorded order book
snapshots yet. `venues.run_multi_venue_backtest` and
`venues.run_cross_venue_validation` both need all three venues' book
histories recorded over the same real time range to produce anything —
that's a genuine gap in this results section, not an oversight, and
exactly what's needed to fill it in:

```
python3 -m lob.run_reconstruction --venues binance coinbase kraken --record-depth-levels 50 --minutes 60

python3 -m venues.run_multi_venue_backtest \
    --binance-book-history lob/raw/binance_book_snapshots.jsonl \
    --coinbase-book-history lob/raw/coinbase_book_snapshots.jsonl \
    --kraken-book-history lob/raw/kraken_book_snapshots.jsonl \
    --side buy --quantity 1.0 --algorithm twap --n-slices 10 \
    --start-offset-seconds 0 --duration-seconds 300 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0

python3 -m venues.run_cross_venue_validation \
    --binance-book-history lob/raw/binance_book_snapshots.jsonl \
    --coinbase-book-history lob/raw/coinbase_book_snapshots.jsonl \
    --kraken-book-history lob/raw/kraken_book_snapshots.jsonl \
    --side buy --quantity 1.0 --n-slices 5 \
    --episode-duration-seconds 60 --stride-seconds 60 \
    --temporary-impact-coef 0.0 --permanent-impact-coef 0.0
```

## What it would take to make this section conclusive rather than illustrative

- **Much longer recordings** (multi-day, ideally spanning different
  real-world sessions/dates) across all three venues at once, so
  `enumerate_episode_windows` has enough real windows per regime to
  bootstrap meaningfully (Section 1 above had exactly one populated
  regime bucket from 5 minutes of data).
- **The Coinbase/Kraken book recordings** described in Section 5.
- **A properly trained RL policy** (tens of thousands of timesteps
  against a real multi-day episode split, not the 2000-timestep smoke
  test in Section 3).
- **Real literature-fitted Almgren-Chriss coefficients**, if a source
  becomes accessible, in place of the square-root-law convention used in
  Section 2 (see `algos/README.md`).

None of that is fabricated here to make this section look more finished
than it is — the gaps above are the honest state of it.
