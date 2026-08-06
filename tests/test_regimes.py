import numpy as np
import pandas as pd

from data.regimes import classify_regimes, rolling_realized_vol


def make_price_df(n=500, seed=0, vol_regimes=None):
    """Synthetic hourly close-price series. `vol_regimes`, if given, is a
    list of (n_bars, sigma) segments so we can construct a series with a
    known calm/volatile structure to check classification against."""
    rng = np.random.default_rng(seed)
    if vol_regimes is None:
        vol_regimes = [(n, 0.01)]
    log_returns = np.concatenate(
        [rng.normal(0, sigma, n_bars) for n_bars, sigma in vol_regimes]
    )
    prices = 100 * np.exp(np.cumsum(log_returns))
    open_time = pd.date_range("2026-01-01", periods=len(prices), freq="h", tz="UTC")
    return pd.DataFrame({"open_time": open_time, "close": prices})


def test_rolling_realized_vol_is_nan_before_window_fills():
    df = make_price_df(n=50)
    vol = rolling_realized_vol(df, window=24, periods_per_year=24 * 365)
    assert vol.iloc[:24].isna().all()
    assert vol.iloc[24:].notna().all()


def test_rolling_realized_vol_scales_with_input_sigma():
    calm = make_price_df(n=300, seed=1, vol_regimes=[(300, 0.001)])
    volatile = make_price_df(n=300, seed=1, vol_regimes=[(300, 0.05)])
    calm_vol = rolling_realized_vol(calm, window=24).dropna().mean()
    volatile_vol = rolling_realized_vol(volatile, window=24).dropna().mean()
    assert volatile_vol > calm_vol * 10


def test_classify_regimes_terciles_are_roughly_balanced():
    df = make_price_df(n=1000, seed=2)
    vol = rolling_realized_vol(df, window=24)
    labels, thresholds = classify_regimes(vol)
    counts = labels.value_counts()
    total = counts.sum()
    for regime in ("calm", "normal", "volatile"):
        # terciles won't be exact due to ties/NaN window warmup, but each
        # should be in the right ballpark
        assert 0.2 < counts.get(regime, 0) / total < 0.45
    assert thresholds["low_threshold"] < thresholds["high_threshold"]


def test_classify_regimes_labels_known_calm_and_volatile_segments():
    # first half calm, second half sharply more volatile -- the back half
    # should dominate the "volatile" bucket.
    df = make_price_df(n=600, seed=3, vol_regimes=[(300, 0.001), (300, 0.05)])
    vol = rolling_realized_vol(df, window=24)
    labels, _ = classify_regimes(vol)
    first_half_volatile_frac = (labels.iloc[:300] == "volatile").mean()
    second_half_volatile_frac = (labels.iloc[300:] == "volatile").mean()
    assert second_half_volatile_frac > first_half_volatile_frac
