"""Real published maker/taker fee schedules for the three venues, base
(lowest, unauthenticated-retail) tier. Verified 2026-08-06.

  - Binance.US: 0% maker, 0.02% taker, flat across all users/pairs, no
    volume tiers -- a fee-structure change effective 2026-04-22. Primary
    source, fetched directly: https://blog.binance.us/zero-fee-trading/
  - Kraken: Tier 1 ($0+ 30-day volume) = 0.40% maker, 0.80% taker.
    Primary source, fetched directly (full 17-tier table retrieved and
    cross-checked for monotonicity): https://www.kraken.com/features/fee-schedule
  - Coinbase Advanced Trade: $0-$10K 30-day volume tier = 0.40% maker,
    0.60% taker. Coinbase's own fee pages (coinbase.com/advanced-fees,
    help.coinbase.com) returned HTTP 403 to direct fetch in this
    environment (bot-blocked) -- these numbers are cross-verified across
    two independent secondary sources that agreed exactly
    (datawallet.com/crypto/coinbase-fees and a second aggregator), not
    fetched from Coinbase directly. Flagged as the one schedule here with
    slightly weaker sourcing than the other two.

Disclosed simplification: these are each venue's *base* retail tier.
Real trading desks with meaningful 30-day volume land in far lower fee
tiers on all three venues (e.g. Kraken's fees fall from 0.80% taker at
Tier 1 to 0.10% at $250M+ volume) -- this project has no real trading
history to determine what tier is realistic for a given backtest, so it
uses the tier every account starts at rather than picking an arbitrary
higher tier to assume.

This project's fill model always crosses the spread (backtest/fill_model.py
walks the book -- it never rests as a maker order), so every simulated
fill is a taker fill. Maker fees are recorded here for completeness/
documentation but aren't applied anywhere in this project's execution
path.

Fee schedules change -- Binance.US's own did, in April 2026, per the
source above. Re-verify before trusting these for anything beyond this
project's own illustrative comparison.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeSchedule:
    venue: str
    maker_fee_bps: float
    taker_fee_bps: float
    source: str


VENUE_FEE_SCHEDULES: dict[str, FeeSchedule] = {
    "binance": FeeSchedule(
        venue="binance", maker_fee_bps=0.0, taker_fee_bps=2.0,
        source="https://blog.binance.us/zero-fee-trading/ (primary, fetched directly)",
    ),
    "coinbase": FeeSchedule(
        venue="coinbase", maker_fee_bps=40.0, taker_fee_bps=60.0,
        source="cross-verified via two independent secondary sources; "
        "coinbase.com/advanced-fees and help.coinbase.com both returned HTTP 403 "
        "to direct fetch in this environment",
    ),
    "kraken": FeeSchedule(
        venue="kraken", maker_fee_bps=40.0, taker_fee_bps=80.0,
        source="https://www.kraken.com/features/fee-schedule (primary, fetched directly, Tier 1)",
    ),
}
