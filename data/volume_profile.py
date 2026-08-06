"""Turns Step 3's time-of-day finding into per-hour weights for VWAP
(Step 6): flat if the ANOVA in `data/time_of_day.py` found no significant
hour-of-day effect, the real empirical hourly shape if it did. This is
where "let the data decide" actually gets enforced in code, rather than
importing equities' U-shaped volume curve as an assumption.
"""

from dataclasses import dataclass

import pandas as pd

from data.time_of_day import check_time_of_day_effect, hourly_volume_profile


@dataclass
class VolumeProfile:
    weights: dict  # hour_utc (0-23) -> normalized weight, sums to 1.0 across all 24 hours
    is_flat: bool  # True: no significant time-of-day effect found, so every hour weighs equally
    tod_test: dict  # the underlying ANOVA result (data/time_of_day.py), kept for transparency


def build_volume_profile(df: pd.DataFrame, alpha: float = 0.05) -> VolumeProfile:
    tod_test = check_time_of_day_effect(df, alpha=alpha)

    if not tod_test["significant_at_alpha"]:
        return VolumeProfile(
            weights={hour: 1 / 24 for hour in range(24)}, is_flat=True, tod_test=tod_test
        )

    profile = hourly_volume_profile(df).reindex(range(24))
    # Hours with no observations at all (possible with a short fetch window)
    # get the overall mean rather than zero weight -- a bucket VWAP has
    # never seen shouldn't be starved of the parent order entirely.
    overall_mean = profile["mean"].mean()
    filled = profile["mean"].fillna(overall_mean)
    total = filled.sum()
    weights = {int(hour): float(value) / total for hour, value in filled.items()}

    return VolumeProfile(weights=weights, is_flat=False, tod_test=tod_test)
