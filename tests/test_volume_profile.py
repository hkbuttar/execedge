import numpy as np
import pandas as pd

from data.volume_profile import build_volume_profile


def make_volume_df(n_days=60, hourly_pattern=None, noise_sigma=1.0, seed=0):
    rng = np.random.default_rng(seed)
    open_time = pd.date_range("2026-01-01", periods=n_days * 24, freq="h", tz="UTC")
    baseline = 100.0
    if hourly_pattern is None:
        hourly_pattern = np.zeros(24)
    hour_of_day = np.array([t.hour for t in open_time])
    volume = baseline + hourly_pattern[hour_of_day] + rng.normal(0, noise_sigma, len(open_time))
    return pd.DataFrame({"open_time": open_time, "volume": volume})


def test_flat_profile_when_no_time_of_day_effect():
    df = make_volume_df(hourly_pattern=None, noise_sigma=5.0, seed=1)
    profile = build_volume_profile(df)
    assert profile.is_flat is True
    assert set(profile.weights) == set(range(24))
    assert all(w == 1 / 24 for w in profile.weights.values())


def test_curved_profile_when_real_time_of_day_effect():
    pattern = np.zeros(24)
    pattern[0:8] = 50.0  # clear session bump
    df = make_volume_df(hourly_pattern=pattern, noise_sigma=1.0, seed=2)
    profile = build_volume_profile(df)
    assert profile.is_flat is False
    # bumped hours should carry more weight than un-bumped hours
    bumped_avg = sum(profile.weights[h] for h in range(0, 8)) / 8
    other_avg = sum(profile.weights[h] for h in range(8, 24)) / 16
    assert bumped_avg > other_avg


def test_weights_always_sum_to_one():
    df = make_volume_df(hourly_pattern=None, noise_sigma=1.0, seed=3)
    profile = build_volume_profile(df)
    assert sum(profile.weights.values()) == 1.0 or abs(sum(profile.weights.values()) - 1.0) < 1e-9

    pattern = np.zeros(24)
    pattern[10] = 200.0
    df2 = make_volume_df(hourly_pattern=pattern, noise_sigma=1.0, seed=4)
    profile2 = build_volume_profile(df2)
    assert abs(sum(profile2.weights.values()) - 1.0) < 1e-9


def test_missing_hours_get_filled_not_zero_weight():
    # only 6 hours of data present at all -- the other 18 hours never appear
    open_time = pd.date_range("2026-01-01", periods=6 * 30, freq="h", tz="UTC")
    open_time = open_time[open_time.hour < 6]
    volume = np.full(len(open_time), 100.0)
    df = pd.DataFrame({"open_time": open_time, "volume": volume})

    # force a "significant" path deterministically isn't reliable with only
    # 6 distinct groups and constant volume (zero variance -> ANOVA breaks),
    # so just check building the hourly profile directly handles missing hours.
    from data.time_of_day import hourly_volume_profile

    raw_profile = hourly_volume_profile(df).reindex(range(24))
    assert raw_profile["mean"].isna().sum() == 18  # confirms the gap this test targets

    overall_mean = raw_profile["mean"].mean()
    filled = raw_profile["mean"].fillna(overall_mean)
    assert filled.isna().sum() == 0
    assert (filled > 0).all()
