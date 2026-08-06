"""Whether BTC/USD volume shows any repeatable hour-of-day pattern at all,
checked directly against real fetched volume bars rather than assumed one
way or the other. Crypto venues never close, so there's no equities-style
open/close volume spike a priori -- but regional session overlap
(Asia/Europe/US) could still produce a real, milder hour-of-day effect.
This module answers that empirically per venue; VWAP's profile shape
(flat vs. hourly-curved) should follow whatever this finds, not an
assumption imported from equities.
"""

import pandas as pd
from scipy import stats


def hourly_volume_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Mean/std/count of volume grouped by hour-of-day (UTC) across every
    day present in `df`. `df["open_time"]` must be timezone-aware UTC
    (as produced by data/fetch_volume.py)."""
    hours = df["open_time"].dt.hour
    profile = df.groupby(hours)["volume"].agg(["mean", "std", "count"])
    profile.index.name = "hour_utc"
    return profile


def check_time_of_day_effect(df: pd.DataFrame, alpha: float = 0.05) -> dict:
    """One-way ANOVA across hour-of-day groups on volume.

    Null hypothesis: mean volume is the same in every hour-of-day bucket
    (no time-of-day effect). Rejecting it (p < alpha) is evidence of a
    real, disclosed pattern in this venue's real data; failing to reject
    it is evidence there's no detectable one here, at this history length
    -- reported either way, not assumed.
    """
    hours = df["open_time"].dt.hour
    groups = [group["volume"].values for _, group in df.groupby(hours)]
    f_stat, p_value = stats.f_oneway(*groups)
    return {
        "f_statistic": float(f_stat),
        "p_value": float(p_value),
        "significant_at_alpha": bool(p_value < alpha),
        "alpha": alpha,
        "n_hour_groups": len(groups),
    }
