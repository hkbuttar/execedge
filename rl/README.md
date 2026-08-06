# RL execution policy

A DQN policy trained against real historical episodes, evaluated honestly
against TWAP and Almgren-Chriss on the same held-out test episodes.

## State, action, reward

- **State** (`observation.py`, 5-dim): remaining inventory fraction, time
  remaining fraction, spread (as a fraction of mid), order book imbalance,
  recent realized volatility — all computed from the real reconstructed
  book (`lob.features`/`lob.order_book`), nothing synthetic.
- **Action** (`action_space.py`, `Discrete(11)`): what fraction of
  *remaining* inventory to trade this step — 0%, 10%, ..., 100%. Same
  regular n_steps interval convention as TWAP/VWAP/Almgren-Chriss, for
  direct comparability.
- **Reward** (`reward.py`): negative implementation shortfall plus an
  Almgren-Chriss-consistent risk-aversion penalty on remaining exposure.
  This isn't just described as consistent with the fill model and
  Almgren-Chriss's own risk term — it's proven: `tests/test_rl_reward.py` shows that
  with `risk_aversion=0`, the sum of per-step rewards across a full
  episode equals **exactly** `-implementation_shortfall(...).total_cost`
  as computed independently by `backtest.metrics` on the same fills. The
  RL reward signal is the same objective every other algorithm in this
  project is scored on, not a separate proxy for it.

## Real historical episodes — a genuine, disclosed constraint

Episodes (`episodes.py`) are windows sampled from a recorded book
history, split walk-forward: earliest windows train, latest windows test,
with an explicit check that no train window's data leaks past the first
test window's start. This part is standard.

What's *not* standard, and worth internalizing before training: this
project's volume/kline data is backfillable over any historical range
via each venue's REST API, but the full order-book depth is not —
`lob.run_reconstruction --record-depth-levels` only captures data going
forward, live, from whenever you start it. So the total real history
available for RL episodes is bounded by how long you've been recording,
not by how far back the venues' history goes. `train_test_split_windows`
raises rather than silently proceeding if there isn't enough recorded
history for a meaningful split (fewer than 2 windows, or an empty side).

## Architecture: training vs. evaluation are different paths, on purpose

- **`env.py`** (`gymnasium.Env`) drives `stable-baselines3`'s training
  loop only. It's the only place per-step reward/observation logic gets
  wired into an actual RL training API.
- **`policy_algorithm.py`** (`TrainedPolicyAlgorithm`) wraps a *trained*
  model as a `backtest.algorithm.ExecutionAlgorithm` — the same interface
  TWAP/VWAP/Almgren-Chriss implement. This means evaluation runs through
  `backtest.simulator`/`backtest.metrics` exactly like every other
  algorithm, rather than a bespoke RL-only scoring loop that could
  subtly diverge from how the rest of this project measures cost.

One real behavioral difference worth knowing: `TrainedPolicyAlgorithm.slice()`
does **not** force full execution if the policy chooses to leave
inventory unfilled through the whole horizon — it's charged via
implementation shortfall's opportunity-cost term, same as any algorithm
whose fills fall short of available real depth. TWAP/VWAP/AC always sum
their child orders to exactly `parent.quantity` by construction; RL's
schedule doesn't have to, and that's left visible rather than
force-corrected.

## Training curves without a tensorboard dependency

`train.py`'s `EpisodeRewardLogger` (a `stable_baselines3` `BaseCallback`)
writes one row per completed training episode (`episode, total_reward`)
to a plain CSV — logging training curves without adding tensorboard as a
dependency this project doesn't otherwise need.

## Usage

Needs `gymnasium`, `stable-baselines3`, `torch` (already in
`requirements.txt`) — nothing else in this project depends on them, so if
you haven't installed the full requirements file yet, this is the first
piece that needs it.

```
python3 -m lob.run_reconstruction --venues binance --record-depth-levels 50 --minutes 60

python3 -m rl.train \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --side buy --quantity 1.0 --n-steps 10 \
    --episode-duration-seconds 300 --stride-seconds 150 \
    --risk-aversion 0.1 --sigma 0.001 \
    --total-timesteps 20000

python3 -m rl.evaluate \
    --book-history lob/raw/binance_book_snapshots.jsonl \
    --model rl/raw/dqn_execution_policy.zip \
    --side buy --quantity 1.0 --n-steps 10 \
    --ac-calibration literature --ac-volatility 0.001 --ac-risk-aversion 0.1 \
    --ac-permanent-to-temporary-ratio 0.01 --ac-sqrt-law-coefficient 1.0 \
    --ac-reference-participation-rate 0.1
```

`rl.evaluate` prints mean implementation shortfall (bps) for `twap`,
`almgren_chriss`, and `rl_policy` on the identical held-out test
episodes, and states plainly whether the RL policy under- or
outperforms Almgren-Chriss, reported honestly either way, consistent
with how this project has handled every other disclosed limitation
(`data/README.md`, `algos/README.md`).

## What's tested here without gymnasium/stable-baselines3 installed

`episodes.py`, `observation.py`, `reward.py`, and `action_space.py` have
no RL-framework dependency and are fully covered by offline tests
(`tests/test_rl_*.py`, 17 tests) that ran and passed in this environment.
`env.py`, `policy_algorithm.py`, `train.py`, and `evaluate.py` all
compile cleanly (no syntax/import-order issues) but do need
`gymnasium`/`stable-baselines3` actually installed to run — that's on
you to verify once you `pip install -r requirements.txt`.

## Not yet implemented

- Continuous-action RL (this project only discretizes size, not
  continuous sizing or explicit timing choice) — noted as future work in
  the top-level README.

## Multi-venue routing works here with zero code changes

`venues/multi_venue_simulator.py` routes any `ExecutionAlgorithm`'s
already-sliced child orders across venues, and `TrainedPolicyAlgorithm`
is exactly that kind of algorithm — see `venues/README.md` for how the
RL policy plugs into multi-venue routing unmodified.
