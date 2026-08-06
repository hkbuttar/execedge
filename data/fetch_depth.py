"""Snapshot real order book depth from each venue and save to data/raw/depth/.

Usage:
    python -m data.fetch_depth [--depth 100]

A snapshot is a point-in-time read of resting liquidity; running this
repeatedly (e.g. on a cron/loop) is how you'd accumulate a real depth
history for later book reconstruction (Step 2).
"""

import argparse
import json
import os
from dataclasses import asdict

from data.config import BTC_USD
from data.exchanges import CLIENTS

RAW_DIR = os.path.join(os.path.dirname(__file__), "raw", "depth")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, default=100, help="order book levels per side")
    parser.add_argument("--out-dir", default=RAW_DIR)
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    for venue, venue_symbol in BTC_USD.items():
        client = CLIENTS[venue]()
        try:
            snapshot = client.fetch_order_book(venue_symbol.symbol, depth=args.depth)
        except Exception as exc:
            print(f"[{venue}] FAILED: {exc}")
            continue

        ts_label = snapshot.timestamp.strftime("%Y%m%dT%H%M%SZ")
        out_path = os.path.join(args.out_dir, f"{venue}_{venue_symbol.symbol}_{ts_label}.json")
        payload = asdict(snapshot)
        payload["timestamp"] = snapshot.timestamp.isoformat()
        with open(out_path, "w") as f:
            json.dump(payload, f)

        best_bid = snapshot.bids[0][0] if snapshot.bids else None
        best_ask = snapshot.asks[0][0] if snapshot.asks else None
        print(
            f"[{venue}] {venue_symbol.symbol}: {len(snapshot.bids)} bid levels, "
            f"{len(snapshot.asks)} ask levels, best bid/ask {best_bid}/{best_ask} "
            f"-> {out_path}"
        )


if __name__ == "__main__":
    main()
