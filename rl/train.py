"""Train a DQN execution policy against real historical episodes sampled
from a recorded book history, with a strict walk-forward train/test split
(rl/episodes.py) -- train on earlier real dates, evaluate on later ones
(rl/evaluate.py), no lookahead.

Needs gymnasium/stable-baselines3/torch installed (requirements.txt) and
a recorded book history with --record-depth-levels > 0
(lob.run_reconstruction). How much real history you need is a genuine,
disclosed constraint, not a knob to tune away: Step 2's live-forward-only
recording (unlike Step 1's backfillable volume/kline history) bounds how
many episode windows exist at all -- enough for a meaningful walk-forward
split needs a recording that spans several multiples of
--episode-duration-seconds.

    python3 -m lob.run_reconstruction --venues binance --record-depth-levels 50 --minutes 60
    python3 -m rl.train \\
        --book-history lob/raw/binance_book_snapshots.jsonl \\
        --side buy --quantity 1.0 --n-steps 10 \\
        --episode-duration-seconds 300 --stride-seconds 150 \\
        --risk-aversion 0.1 --sigma 0.001 \\
        --total-timesteps 20000
"""

import argparse
import csv
import json
import os

from stable_baselines3 import DQN
from stable_baselines3.common.callbacks import BaseCallback

from backtest.book_history import BookHistoryReader
from rl.env import ExecutionEnv
from rl.episodes import enumerate_episode_windows, train_test_split_windows


class EpisodeRewardLogger(BaseCallback):
    """Logs total reward per completed training episode to CSV -- Step 8's
    "log training curves" requirement, without pulling in a tensorboard
    dependency this project doesn't otherwise need."""

    def __init__(self, csv_path: str):
        super().__init__()
        self._csv_path = csv_path
        self._episode_reward = 0.0
        self._episode_count = 0
        self._file = None
        self._writer = None

    def _on_training_start(self):
        self._file = open(self._csv_path, "w", newline="")
        self._writer = csv.writer(self._file)
        self._writer.writerow(["episode", "total_reward"])

    def _on_step(self) -> bool:
        self._episode_reward += float(self.locals["rewards"][0])
        if self.locals["dones"][0]:
            self._episode_count += 1
            self._writer.writerow([self._episode_count, self._episode_reward])
            self._file.flush()
            self._episode_reward = 0.0
        return True

    def _on_training_end(self):
        if self._file:
            self._file.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-history", required=True)
    parser.add_argument("--side", choices=["buy", "sell"], required=True)
    parser.add_argument("--quantity", type=float, required=True)
    parser.add_argument("--n-steps", type=int, default=10)
    parser.add_argument("--episode-duration-seconds", type=float, required=True)
    parser.add_argument("--stride-seconds", type=float, required=True)
    parser.add_argument("--train-fraction", type=float, default=0.7)
    parser.add_argument("--risk-aversion", type=float, required=True)
    parser.add_argument("--sigma", type=float, required=True)
    parser.add_argument("--total-timesteps", type=int, default=20000)
    parser.add_argument("--model-out", default="rl/raw/dqn_execution_policy.zip")
    parser.add_argument("--reward-log-out", default="rl/raw/training_rewards.csv")
    args = parser.parse_args()

    book_history = BookHistoryReader(args.book_history)
    windows = enumerate_episode_windows(book_history, args.episode_duration_seconds, args.stride_seconds)
    train_windows, test_windows = train_test_split_windows(windows, args.train_fraction)
    print(f"{len(windows)} total episode windows -> {len(train_windows)} train / {len(test_windows)} test")

    env = ExecutionEnv(
        book_history, train_windows, args.quantity, args.side, args.n_steps, args.risk_aversion, args.sigma
    )

    os.makedirs(os.path.dirname(args.model_out) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(args.reward_log_out) or ".", exist_ok=True)

    model = DQN("MlpPolicy", env, verbose=1)
    model.learn(total_timesteps=args.total_timesteps, callback=EpisodeRewardLogger(args.reward_log_out))
    model.save(args.model_out)
    print(f"saved model -> {args.model_out}")
    print(f"training reward curve -> {args.reward_log_out}")

    # Persisted so rl.evaluate uses the exact same held-out windows this
    # run trained without, rather than re-enumerating (and potentially
    # drifting from) the split.
    test_windows_path = os.path.splitext(args.model_out)[0] + "_test_windows.json"
    with open(test_windows_path, "w") as f:
        json.dump(
            [{"start": w.start_time.isoformat(), "end": w.end_time.isoformat()} for w in test_windows], f
        )
    print(f"test windows -> {test_windows_path}")


if __name__ == "__main__":
    main()
