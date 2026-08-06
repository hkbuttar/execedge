"""Run regime classification and the time-of-day check against real
volume data already fetched via `python3 -m data.fetch_volume`.

Needs enough history for both analyses to be meaningful: the rolling-vol
window needs several multiples of itself to produce a stable tercile
split, and the hour-of-day ANOVA needs many observations per hour bucket
across many distinct days (a handful of days won't separate a real
pattern from noise). --days 30 or more when fetching is a reasonable
starting point; the printed sample sizes below make it obvious if there
isn't enough data yet rather than silently producing an unreliable split.

Usage:
    python3 -m data.analyze_regimes --interval 60 --vol-window 24
"""

import argparse
import json
import os

import pandas as pd

from data.config import BTC_USD
from data.regimes import classify_regimes, rolling_realized_vol
from data.time_of_day import check_time_of_day_effect, hourly_volume_profile

VOLUME_DIR = os.path.join(os.path.dirname(__file__), "raw", "volume")
OUT_DIR = os.path.join(os.path.dirname(__file__), "raw", "regimes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval", type=int, default=60,
        help="bar size in minutes, must match the fetched volume CSV filenames",
    )
    parser.add_argument(
        "--vol-window", type=int, default=24,
        help="rolling realized-vol window, in bars (default 24 bars = 1 day at 60m)",
    )
    parser.add_argument("--volume-dir", default=VOLUME_DIR)
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    periods_per_year = int(365 * 24 * 60 / args.interval)

    for venue, venue_symbol in BTC_USD.items():
        path = os.path.join(
            args.volume_dir, f"{venue}_{venue_symbol.symbol}_{args.interval}m.csv"
        )
        if not os.path.exists(path):
            print(f"[{venue}] no volume data at {path} -- run `python3 -m data.fetch_volume` first")
            continue

        df = pd.read_csv(path, parse_dates=["open_time"])
        df = df.sort_values("open_time").reset_index(drop=True)

        if len(df) < args.vol_window * 3:
            print(
                f"[{venue}] only {len(df)} bars fetched; need at least "
                f"{args.vol_window * 3} for a stable tercile split -- fetch more history first"
            )
            continue

        vol = rolling_realized_vol(df, window=args.vol_window, periods_per_year=periods_per_year)
        labels, thresholds = classify_regimes(vol)
        regime_counts = labels.value_counts(dropna=True).to_dict()

        profile = hourly_volume_profile(df)
        tod_test = check_time_of_day_effect(df)

        out = df[["open_time"]].copy()
        out["realized_vol"] = vol
        out["regime"] = labels
        out.to_csv(os.path.join(args.out_dir, f"{venue}_regimes.csv"), index=False)

        with open(os.path.join(args.out_dir, f"{venue}_time_of_day.json"), "w") as f:
            json.dump(
                {
                    "hourly_profile": profile.reset_index().to_dict(orient="records"),
                    "anova_test": tod_test,
                },
                f,
                indent=2,
            )

        print(f"[{venue}] {len(df)} bars, vol window={args.vol_window} bars")
        print(f"[{venue}] regime thresholds: {thresholds}")
        print(f"[{venue}] regime counts: {regime_counts}")
        print(
            f"[{venue}] time-of-day ANOVA: F={tod_test['f_statistic']:.3f} "
            f"p={tod_test['p_value']:.4f} significant={tod_test['significant_at_alpha']} "
            f"(n_hour_groups={tod_test['n_hour_groups']})"
        )


if __name__ == "__main__":
    main()
