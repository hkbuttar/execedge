"""Real historical episode windows for the RL execution environment, and
a strict walk-forward train/test split by date range -- train on earlier
real dates, evaluate on later ones, no lookahead. Same discipline
referenced from alpha-signal-lab.

Worth stating plainly: this is genuinely limited by how long you've been
recording a book history. Step 1's volume/kline data is backfillable over
any historical range via each venue's REST API; Step 2's full order-book
depth is not -- `lob.run_reconstruction --record-depth-levels` only
captures data going forward, live, from whenever you start it. So the
total real history available for RL episodes here is bounded by that
recording's duration, not by how far back the venues' history goes. Train
and test both come from the same single recorded stretch, split
chronologically.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from backtest.book_history import BookHistoryReader


@dataclass(frozen=True)
class EpisodeWindow:
    start_time: datetime
    end_time: datetime


def enumerate_episode_windows(
    book_history: BookHistoryReader, episode_duration_seconds: float, stride_seconds: float
) -> list:
    """All windows of `episode_duration_seconds` fitting within the
    recorded history, starting every `stride_seconds` (overlapping
    windows if stride < duration -- more samples, at the cost of episodes
    sharing real market data with their neighbors)."""
    if episode_duration_seconds <= 0 or stride_seconds <= 0:
        raise ValueError("episode_duration_seconds and stride_seconds must both be positive")

    windows = []
    t = book_history.start_time
    duration = timedelta(seconds=episode_duration_seconds)
    stride = timedelta(seconds=stride_seconds)
    while t + duration <= book_history.end_time:
        windows.append(EpisodeWindow(start_time=t, end_time=t + duration))
        t += stride
    return windows


def train_test_split_windows(windows: list, train_fraction: float = 0.7) -> tuple:
    """Chronological split: the earliest `train_fraction` of windows (by
    start_time -- `windows` is assumed already ascending, as
    `enumerate_episode_windows` produces) become train, the rest become
    test. Raises rather than silently proceeding if there's too little
    recorded history for a meaningful split, or if the split would leak
    a train window's data into the test period.
    """
    if len(windows) < 2:
        raise ValueError(
            f"only {len(windows)} episode window(s) available from the recorded book "
            f"history -- need at least 2 (one train, one test) for a walk-forward split. "
            f"Record a longer book history, or shorten --episode-duration-seconds / "
            f"--stride-seconds so more windows fit in what's already recorded."
        )
    if not 0 < train_fraction < 1:
        raise ValueError(f"train_fraction must be in (0, 1), got {train_fraction}")

    split_idx = max(1, min(len(windows) - 1, round(len(windows) * train_fraction)))
    train_windows, test_windows = windows[:split_idx], windows[split_idx:]

    if not train_windows or not test_windows:
        raise ValueError("train/test split produced an empty side -- adjust train_fraction")
    if train_windows[-1].end_time > test_windows[0].start_time:
        raise ValueError(
            "train and test windows overlap in time -- this would leak future "
            "information into training. Use a smaller --stride-seconds relative to "
            "--episode-duration-seconds, or fewer overlapping windows."
        )
    return train_windows, test_windows
