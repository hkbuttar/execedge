"""Calm/normal/volatile regime classification from real rolling realized
volatility, computed from historical kline close prices (data/fetch_volume.py's
output).

Threshold choice, stated explicitly rather than left implicit: regimes
are terciles of the rolling-vol series' own empirical distribution over
whatever history is fetched (bottom third = calm, top third = volatile,
middle third = normal). This is a relative, sample-dependent split, not a
fixed volatility level -- refetching more/less history, or a different
date range, shifts the thresholds. That's a deliberate tradeoff: an
absolute threshold would need an external reference vol level this
project has no principled way to pick for crypto, whereas terciles always
partition the sample into three comparably-sized regimes for Step 11's
per-regime statistics to run on.
"""

import numpy as np
import pandas as pd

REGIME_LABELS = ("calm", "normal", "volatile")


def rolling_realized_vol(
    df: pd.DataFrame, window: int = 24, periods_per_year: int = 24 * 365
) -> pd.Series:
    """Annualized rolling realized volatility of log returns on `df["close"]`.

    `window` is in bars, not calendar time -- the caller is responsible
    for passing a fixed-interval dataframe (e.g. hourly bars) and an
    annualization factor consistent with that interval, since bars are
    evenly spaced but calendar time between them isn't guaranteed if any
    bars are missing.
    """
    log_returns = np.log(df["close"] / df["close"].shift(1))
    rolling_std = log_returns.rolling(window=window, min_periods=window).std()
    return rolling_std * np.sqrt(periods_per_year)


def classify_regimes(
    vol: pd.Series, low_q: float = 1 / 3, high_q: float = 2 / 3
) -> tuple[pd.Series, dict]:
    """Bucket a rolling-vol series into terciles. Returns (labels, thresholds)
    -- thresholds are the actual quantile values used, so the split is
    auditable rather than a magic number buried in the classification.
    """
    valid = vol.dropna()
    low_thresh = valid.quantile(low_q)
    high_thresh = valid.quantile(high_q)

    def label(v):
        if pd.isna(v):
            return None
        if v <= low_thresh:
            return "calm"
        if v >= high_thresh:
            return "volatile"
        return "normal"

    labels = vol.apply(label)
    thresholds = {
        "low_quantile": low_q,
        "high_quantile": high_q,
        "low_threshold": float(low_thresh),
        "high_threshold": float(high_thresh),
    }
    return labels, thresholds
