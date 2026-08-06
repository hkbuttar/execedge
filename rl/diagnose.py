"""Print a diagnostic report for a completed rl.train run.

    python3 -m rl.train --book-history ... --total-timesteps 20000
    python3 -m rl.diagnose --rewards-csv rl/raw/training_rewards.csv

Reports honestly: if the run's late-training reward isn't better than its
early-training reward, that's exactly what gets printed. This doesn't
diagnose *why* (hyperparameters, episode count, reward shaping) -- it
just flags whether the run is worth looking at further.
"""

import argparse

from rl.diagnostics import diagnose_training_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rewards-csv", default="rl/raw/training_rewards.csv")
    parser.add_argument(
        "--window-fraction", type=float, default=0.2,
        help="fraction of episodes at each end used for the early/late comparison",
    )
    args = parser.parse_args()

    result = diagnose_training_run(args.rewards_csv, window_fraction=args.window_fraction)

    print(f"{result.n_episodes} completed episodes")
    print(f"reward: mean={result.mean_reward:.4f} std={result.std_reward:.4f} "
          f"min={result.min_reward:.4f} max={result.max_reward:.4f}")
    print(f"early-window mean reward: {result.early_mean_reward:.4f}")
    print(f"late-window mean reward:  {result.late_mean_reward:.4f}")

    if result.has_nan_or_inf:
        print("WARNING: NaN or inf found in the reward log -- training likely diverged")

    if result.improved:
        print("reward improved from early to late training -- worth evaluating further")
    else:
        print("reward did NOT improve from early to late training -- reported as-is, "
              "not worth trusting this policy without investigating why")


if __name__ == "__main__":
    main()
