"""Connect to real venue feeds, reconstruct each order book live, and
append computed microstructure features to JSONL for later analysis
(Step 3 regime identification, Step 6 volume/feature joins).

This is a long-running process (holds open websocket connections) -- run
it yourself for however long you want a feature history for:

    python3 -m lob.run_reconstruction --venues binance coinbase kraken --minutes 30

Ctrl-C to stop; each venue's reconciler runs in its own thread.
"""

import argparse
import json
import os
import time
from dataclasses import asdict

from lob.features import RealizedVolTracker, compute_features
from lob.reconcile.binance import BinanceBookReconciler
from lob.reconcile.coinbase import CoinbaseBookReconciler
from lob.reconcile.kraken import KrakenBookReconciler

OUT_DIR = os.path.join(os.path.dirname(__file__), "raw")

SYMBOLS = {"binance": "BTCUSDT", "coinbase": "BTC-USD", "kraken": "BTC/USD"}
RECONCILERS = {
    "binance": BinanceBookReconciler,
    "coinbase": CoinbaseBookReconciler,
    "kraken": KrakenBookReconciler,
}


def make_writer(venue: str, out_dir: str):
    path = os.path.join(out_dir, f"{venue}_features.jsonl")
    f = open(path, "a")
    vol_tracker = RealizedVolTracker()

    def on_update(book):
        snapshot = compute_features(book, vol_tracker)
        row = asdict(snapshot)
        row["timestamp"] = snapshot.timestamp.isoformat() if snapshot.timestamp else None
        f.write(json.dumps(row) + "\n")
        f.flush()

    return on_update, path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venues", nargs="+", default=list(RECONCILERS), choices=list(RECONCILERS))
    parser.add_argument("--minutes", type=float, default=None, help="stop after N minutes (default: run until Ctrl-C)")
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    threads = []
    for venue in args.venues:
        reconciler = RECONCILERS[venue](SYMBOLS[venue])
        on_update, path = make_writer(venue, args.out_dir)
        print(f"[{venue}] connecting, writing features -> {path}")
        threads.append(reconciler.start(on_update=on_update))

    if args.minutes is not None:
        time.sleep(args.minutes * 60)
        print("time limit reached, exiting (threads are daemons and will stop with the process)")
        return

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
