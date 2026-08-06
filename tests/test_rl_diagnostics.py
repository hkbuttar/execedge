import math

import pandas as pd
import pytest

from rl.diagnostics import diagnose_training_run


def make_df(rewards):
    return pd.DataFrame({"episode": range(1, len(rewards) + 1), "total_reward": rewards})


def test_raises_with_fewer_than_two_episodes():
    with pytest.raises(ValueError):
        diagnose_training_run(make_df([1.0]))


def test_detects_improvement_over_training():
    # rewards clearly trending up from early to late episodes
    rewards = [-10.0, -9.0, -8.0, -7.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0]
    result = diagnose_training_run(make_df(rewards))
    assert result.improved is True
    assert result.late_mean_reward > result.early_mean_reward
    assert result.n_episodes == 10


def test_detects_no_improvement():
    rewards = [4.0, 3.0, 2.0, 1.0, 0.0, -1.0, -7.0, -8.0, -9.0, -10.0]
    result = diagnose_training_run(make_df(rewards))
    assert result.improved is False


def test_summary_stats_match_the_data():
    rewards = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = diagnose_training_run(make_df(rewards))
    assert result.mean_reward == pytest.approx(3.0)
    assert result.min_reward == 1.0
    assert result.max_reward == 5.0


def test_detects_nan_blowup():
    rewards = [1.0, 2.0, float("nan"), 4.0, 5.0]
    result = diagnose_training_run(make_df(rewards))
    assert result.has_nan_or_inf is True


def test_detects_inf_blowup():
    rewards = [1.0, 2.0, float("inf"), 4.0, 5.0]
    result = diagnose_training_run(make_df(rewards))
    assert result.has_nan_or_inf is True


def test_no_false_positive_blowup_on_clean_data():
    rewards = [1.0, -2.0, 3.5, -4.25, 5.0]
    result = diagnose_training_run(make_df(rewards))
    assert result.has_nan_or_inf is False


def test_accepts_csv_path(tmp_path):
    path = tmp_path / "rewards.csv"
    make_df([1.0, 2.0, 3.0, 4.0]).to_csv(path, index=False)
    result = diagnose_training_run(str(path))
    assert result.n_episodes == 4
    assert result.mean_reward == pytest.approx(2.5)


def test_window_fraction_controls_early_late_split():
    rewards = list(range(10))  # 0..9
    result = diagnose_training_run(make_df(rewards), window_fraction=0.5)
    assert result.early_mean_reward == pytest.approx(sum(range(5)) / 5)
    assert result.late_mean_reward == pytest.approx(sum(range(5, 10)) / 5)
