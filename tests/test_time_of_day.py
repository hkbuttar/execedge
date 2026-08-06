import numpy as np
import pandas as pd

from data.time_of_day import check_time_of_day_effect, hourly_volume_profile


def make_volume_df(n_days=30, hourly_pattern=None, noise_sigma=1.0, seed=0):
    """Synthetic hourly volume series over `n_days` days. `hourly_pattern`,
    if given, is a length-24 array of per-hour mean volume added on top of
    a flat baseline + noise -- lets us construct both a "real pattern"
    case and a "no pattern" (flat, noise-only) case."""
    rng = np.random.default_rng(seed)
    open_time = pd.date_range("2026-01-01", periods=n_days * 24, freq="h", tz="UTC")
    baseline = 100.0
    if hourly_pattern is None:
        hourly_pattern = np.zeros(24)
    hour_of_day = np.array([t.hour for t in open_time])
    volume = baseline + hourly_pattern[hour_of_day] + rng.normal(0, noise_sigma, len(open_time))
    return pd.DataFrame({"open_time": open_time, "volume": volume})


def test_hourly_volume_profile_shape():
    df = make_volume_df(n_days=10)
    profile = hourly_volume_profile(df)
    assert len(profile) == 24
    assert (profile["count"] == 10).all()


def test_no_time_of_day_effect_fails_to_reject_null():
    df = make_volume_df(n_days=60, hourly_pattern=None, noise_sigma=5.0, seed=1)
    result = check_time_of_day_effect(df)
    assert result["significant_at_alpha"] is False


def test_strong_time_of_day_effect_rejects_null():
    pattern = np.zeros(24)
    pattern[0:8] = 50.0  # a clear "Asia session" style bump
    df = make_volume_df(n_days=60, hourly_pattern=pattern, noise_sigma=1.0, seed=2)
    result = check_time_of_day_effect(df)
    assert result["significant_at_alpha"] is True
    assert result["p_value"] < 0.01
