import json
from datetime import datetime, timedelta, timezone

import pytest

from backtest.book_history import BookHistoryReader
from rl.episodes import enumerate_episode_windows, train_test_split_windows

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def write_history(path, n_snapshots, interval_seconds):
    with open(path, "w") as f:
        for i in range(n_snapshots):
            ts = START + timedelta(seconds=i * interval_seconds)
            row = {
                "venue": "test", "symbol": "BTCUSD", "timestamp": ts.isoformat(),
                "bids": [[99.0, 1.0]], "asks": [[100.0, 1.0]],
            }
            f.write(json.dumps(row) + "\n")


def test_enumerate_windows_covers_full_history_without_exceeding_it(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n_snapshots=601, interval_seconds=1)  # 0..600s
    book_history = BookHistoryReader.from_file(str(path))

    windows = enumerate_episode_windows(book_history, episode_duration_seconds=100, stride_seconds=100)

    assert len(windows) == 6  # [0,100),[100,200),...,[500,600]
    assert windows[0].start_time == book_history.start_time
    assert all(w.end_time <= book_history.end_time for w in windows)


def test_enumerate_windows_overlap_with_small_stride(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n_snapshots=201, interval_seconds=1)
    book_history = BookHistoryReader.from_file(str(path))

    windows = enumerate_episode_windows(book_history, episode_duration_seconds=100, stride_seconds=50)
    assert len(windows) > (200 // 100)  # overlapping windows produce more samples than non-overlapping


def test_enumerate_windows_rejects_non_positive_args(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n_snapshots=10, interval_seconds=1)
    book_history = BookHistoryReader.from_file(str(path))
    with pytest.raises(ValueError):
        enumerate_episode_windows(book_history, episode_duration_seconds=0, stride_seconds=10)
    with pytest.raises(ValueError):
        enumerate_episode_windows(book_history, episode_duration_seconds=10, stride_seconds=-1)


def test_split_is_chronological_and_non_overlapping(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n_snapshots=1001, interval_seconds=1)
    book_history = BookHistoryReader.from_file(str(path))
    windows = enumerate_episode_windows(book_history, episode_duration_seconds=100, stride_seconds=100)

    train, test = train_test_split_windows(windows, train_fraction=0.7)

    assert train[-1].end_time <= test[0].start_time
    assert len(train) + len(test) == len(windows)
    assert all(a.start_time < b.start_time for a, b in zip(train, train[1:]))
    assert all(a.start_time < b.start_time for a, b in zip(test, test[1:]))


def test_split_raises_with_fewer_than_two_windows(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n_snapshots=50, interval_seconds=1)
    book_history = BookHistoryReader.from_file(str(path))
    windows = enumerate_episode_windows(book_history, episode_duration_seconds=100, stride_seconds=100)
    assert len(windows) < 2
    with pytest.raises(ValueError):
        train_test_split_windows(windows, train_fraction=0.7)


def test_split_rejects_invalid_train_fraction(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n_snapshots=1001, interval_seconds=1)
    book_history = BookHistoryReader.from_file(str(path))
    windows = enumerate_episode_windows(book_history, episode_duration_seconds=100, stride_seconds=100)
    with pytest.raises(ValueError):
        train_test_split_windows(windows, train_fraction=0.0)
    with pytest.raises(ValueError):
        train_test_split_windows(windows, train_fraction=1.0)


def test_split_rejects_overlapping_train_test_windows(tmp_path):
    path = tmp_path / "history.jsonl"
    write_history(path, n_snapshots=301, interval_seconds=1)
    book_history = BookHistoryReader.from_file(str(path))
    # small stride relative to duration -> heavy overlap between adjacent windows
    windows = enumerate_episode_windows(book_history, episode_duration_seconds=100, stride_seconds=10)
    with pytest.raises(ValueError):
        train_test_split_windows(windows, train_fraction=0.7)
