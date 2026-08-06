"""Training diagnostics for a completed RL training run: analyzes
`rl.train`'s episode-reward log (`EpisodeRewardLogger`'s CSV output) for
basic sanity -- did reward actually improve, is there a NaN/inf blowup,
what's the overall spread. Pure data analysis, no gymnasium/stable-
baselines3 dependency, so this runs (and is tested) even in environments
where those aren't installed -- unlike training itself.

This deliberately doesn't try to diagnose *why* training did or didn't
work (that needs domain judgment: reward shaping, hyperparameters,
episode count); it flags whether the run is even worth looking at
further, honestly, including the "no, it didn't improve" case.
"""

import math
from dataclasses import dataclass

import pandas as pd


@dataclass
class TrainingDiagnostics:
    n_episodes: int
    mean_reward: float
    std_reward: float
    min_reward: float
    max_reward: float
    early_mean_reward: float  # mean over the first `window` episodes
    late_mean_reward: float  # mean over the last `window` episodes
    improved: bool  # late_mean_reward > early_mean_reward
    has_nan_or_inf: bool


def diagnose_training_run(rewards, window_fraction: float = 0.2) -> TrainingDiagnostics:
    """`rewards` is either a path to `rl.train`'s CSV output, or an
    already-loaded DataFrame with a `total_reward` column."""
    df = rewards if isinstance(rewards, pd.DataFrame) else pd.read_csv(rewards)
    if len(df) < 2:
        raise ValueError(
            f"need at least 2 completed episodes to diagnose a training run, got {len(df)}"
        )

    series = df["total_reward"]
    has_nan_or_inf = bool(series.isna().any() or series.apply(lambda v: math.isinf(v)).any())

    window = max(1, int(len(series) * window_fraction))
    early_mean = float(series.iloc[:window].mean())
    late_mean = float(series.iloc[-window:].mean())

    return TrainingDiagnostics(
        n_episodes=len(series),
        mean_reward=float(series.mean()),
        std_reward=float(series.std()),
        min_reward=float(series.min()),
        max_reward=float(series.max()),
        early_mean_reward=early_mean,
        late_mean_reward=late_mean,
        improved=late_mean > early_mean,
        has_nan_or_inf=has_nan_or_inf,
    )
