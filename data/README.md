# Data

Real order book depth and volume data for BTC/USD from three venues:
Binance (via Binance.US, see below), Coinbase, and Kraken. All three
expose public, unauthenticated REST endpoints for both order book depth
and historical klines/candles — **no API keys are required anywhere in
this project's data layer.**

| Venue    | Depth endpoint                                   | Volume endpoint                                     | Symbol   |
|----------|---------------------------------------------------|------------------------------------------------------|----------|
| Binance  | `api.binance.us/api/v3/depth`                     | `api.binance.us/api/v3/klines`                        | `BTCUSDT`|
| Coinbase | `api.exchange.coinbase.com/products/.../book`     | `api.exchange.coinbase.com/products/.../candles`      | `BTC-USD`|
| Kraken   | `api.kraken.com/0/public/Depth`                   | `api.kraken.com/0/public/OHLC`                        | `XBTUSD` |

## Disclosed substitution: Binance.US, not global Binance

`api.binance.com` (global Binance) returns HTTP 451 ("restricted location")
from US-based infrastructure, which is where this project's development
and deployment (Render) both run. **Binance.US (`api.binance.us`) is used
instead** — a legally separate exchange with its own order book, not a
mirror of global Binance's. It is real, live, unauthenticated market data,
but two consequences follow and are worth stating plainly rather than
letting "Binance" imply the deepest, most liquid book in crypto:

- Binance.US lists far fewer pairs and carries materially thinner depth
  and volume than global Binance.
- Any claim of "Binance as the primary/most-liquid venue" in this
  project's results should be read as "Binance.US among the three venues
  actually used," not as a claim about global Binance's book.

## Per-venue conventions

- **Tick/lot size**: each venue enforces its own minimum price increment
  and minimum order size for BTC/USD (exposed via each venue's
  `exchangeInfo`-equivalent endpoint); these aren't hardcoded here yet and
  should be pulled per-venue before the order-slicing simulator needs to
  round child-order sizes/prices.
- **Depth snapshot semantics**: Binance and Coinbase return price-level-
  aggregated books (multiple orders at a price level are summed) at the
  requested depth. Kraken's `Depth` endpoint is also aggregated by price
  level. All three are therefore comparable "L2" snapshots — none of the
  three clients here pull L3 (order-by-order) data, though Coinbase
  exposes an L3 endpoint if that granularity is ever needed.
- **Kline/candle granularity**: the three venues support different native
  bar sizes (Binance: 1/3/5/15/30m, 1/2/4/6/8/12h, 1d, 3d, 1w; Coinbase:
  60/300/900/3600/21600/86400s; Kraken: 1/5/15/30/60/240/1440/10080/21600
  minutes). **60 minutes is the largest interval every venue supports
  natively**, so cross-venue volume-profile comparisons (regime
  identification, VWAP) should default to hourly bars unless a finer
  interval is confirmed supported on all venues in use.
- **Kraken pair-name quirk**: requesting pair `XBTUSD` returns results
  keyed under an internal name (`XXBTZUSD`); the client reads the first
  key of the response rather than assuming the request symbol round-trips.

## 24/7 trading — no open/close volume curve

Unlike equities, none of these venues ever close, so there's no
market-open/market-close volume spike the way equities have. Whether
crypto BTC/USD still shows *any* repeatable intraday (hour-of-day) volume
pattern — driven by regional trading-session overlap (Asia/Europe/US) even
without a formal open/close — is an open, disclosed empirical question,
not an assumption. This project checks it directly against real volume
data before VWAP's profile is built flat or curved.

## Impact parameter estimates (placeholder — finalized in the Almgren-Chriss module)

The Almgren-Chriss (2000) framework parameterizes execution cost with a
permanent impact term (linear in trade size, moves the reference price
persistently) and a temporary impact term (linear or power-law in trade
*rate*, decays after each child order). The original paper's own
coefficients are calibrated to a specific hypothetical equity and are not
a universal constant; follow-up empirical microstructure work (e.g. the
"square-root law" of impact — cost scaling with volatility times the
square root of participation rate — appears across both equities research
and at least one direct empirical study of Bitcoin metaorders) gives the
functional form more credibility than any single numeric coefficient.

This project will:
1. Pull specific published coefficient values (with citations) when the
   Almgren-Chriss implementation lands, flagged explicitly as
   **equities-derived, applied to crypto as a disclosed cross-asset-class
   assumption.**
2. Separately estimate coefficients directly from this project's own
   reconstructed real order book (Almgren-Chriss's empirical calibration),
   and compare the two — divergence between them is itself a result
   worth reporting, not just a calibration detail.

No numeric values are hardcoded yet; this section exists so the
Almgren-Chriss module has a documented starting point rather than an
unstated assumption.

## Regime identification & the time-of-day question

`data/regimes.py` computes rolling realized volatility (annualized std of
log returns over a bar window, e.g. 24 hourly bars = 1 day) from
`fetch_volume`'s output, then splits it into **calm / normal / volatile**
terciles of that series' own empirical distribution. This is a relative,
sample-dependent threshold, stated explicitly rather than left implicit:
refetching a different date range shifts the cutoffs. An absolute vol
threshold was considered and rejected — there's no principled external
reference level for crypto the way there might be for, say, VIX regimes
in equities, whereas terciles always give the statistical-rigor layer
three comparably-sized buckets to run per-regime statistics on.

`data/time_of_day.py` runs a one-way ANOVA testing whether mean volume
differs by hour-of-day (UTC) — the genuinely open empirical question
flagged above ("24/7 trading — no open/close volume curve"), since 24/7
trading has no open/close spike to assume one way or the other. A significant result
(p < 0.05) is evidence of a real regional-session pattern (Asia/Europe/US
overlap); a null result is evidence there isn't a detectable one over the
fetched history. Whichever way it comes out per venue directly decides
VWAP's profile shape --
`data/volume_profile.py` consumes this test's result directly to build
`algos/vwap.py`'s per-hour weights, flat or curved accordingly.

Both modules are covered by offline unit tests against synthetic data
with known ground truth (`tests/test_regimes.py`, `tests/test_time_of_day.py`)
— they don't need a network connection to verify the statistics are
computed correctly, only real data to know what BTC/USD actually does.

Run after fetching enough volume history (30+ days recommended so the
ANOVA has enough per-hour observations to be meaningful):

```
python3 -m data.fetch_volume --days 30 --interval 60
python3 -m data.analyze_regimes --interval 60 --vol-window 24
```

Output: `data/raw/regimes/{venue}_regimes.csv` (per-bar vol + regime
label) and `data/raw/regimes/{venue}_time_of_day.json` (hourly profile +
ANOVA result).

## Layout

```
data/
├── config.py              # venue/symbol definitions
├── exchanges/
│   ├── base.py             # ExchangeClient interface, OrderBookSnapshot/Kline schemas
│   ├── binance.py
│   ├── coinbase.py
│   └── kraken.py
├── fetch_depth.py          # CLI: snapshot depth from all venues -> data/raw/depth/
├── fetch_volume.py         # CLI: pull historical klines from all venues -> data/raw/volume/
├── regimes.py              # rolling realized vol + calm/normal/volatile tercile classification
├── time_of_day.py          # hour-of-day volume ANOVA (is there a real pattern, or not)
├── volume_profile.py       # turns the ANOVA result into VWAP's per-hour weights (flat or curved)
├── analyze_regimes.py      # CLI: runs regimes + time-of-day against fetched volume data
└── raw/                    # gitignored; populated by the scripts above
```

## Usage

```
pip install -r requirements.txt
python3 -m data.fetch_depth
python3 -m data.fetch_volume --days 7 --interval 60
```
