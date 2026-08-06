"""Pull real historical intraday volume bars (klines/candles) from each venue
and save to data/raw/volume/ as CSV, for VWAP profile construction (Step 6)
and regime identification (Step 3).

Usage:
    python -m data.fetch_volume --days 7 --interval 60
"""

import argparse
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

from data.config import BTC_USD
from data.exchanges import CLIENTS

RAW_DIR = os.path.join(os.path.dirname(__file__), "raw", "volume")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="lookback window in days")
    parser.add_argument(
        "--interval", type=int, default=60, help="bar size in minutes (must be a "
        "granularity every venue supports; 60 works on all three)"
    )
    parser.add_argument("--out-dir", default=RAW_DIR)
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)

    for venue, venue_symbol in BTC_USD.items():
        client = CLIENTS[venue]()
        try:
            klines = client.fetch_klines(venue_symbol.symbol, args.interval, start, end)
        except Exception as exc:
            print(f"[{venue}] FAILED: {exc}")
            continue

        if not klines:
            print(f"[{venue}] no data returned")
            continue

        df = pd.DataFrame([k.__dict__ for k in klines])
        out_path = os.path.join(
            args.out_dir, f"{venue}_{venue_symbol.symbol}_{args.interval}m.csv"
        )
        df.to_csv(out_path, index=False)
        print(
            f"[{venue}] {venue_symbol.symbol}: {len(df)} bars "
            f"({df['open_time'].min()} -> {df['open_time'].max()}) -> {out_path}"
        )


if __name__ == "__main__":
    main()
