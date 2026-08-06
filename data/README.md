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
  should be pulled per-venue before the order-slicing simulator (Step 4)
  needs to round child-order sizes/prices.
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
  natively**, so cross-venue volume-profile comparisons (Step 3, Step 6)
  should default to hourly bars unless a finer interval is confirmed
  supported on all venues in use.
- **Kraken pair-name quirk**: requesting pair `XBTUSD` returns results
  keyed under an internal name (`XXBTZUSD`); the client reads the first
  key of the response rather than assuming the request symbol round-trips.

## 24/7 trading — no open/close volume curve

Unlike equities, none of these venues ever close, so there's no
market-open/market-close volume spike the way equities have. Whether
crypto BTC/USD still shows *any* repeatable intraday (hour-of-day) volume
pattern — driven by regional trading-session overlap (Asia/Europe/US) even
without a formal open/close — is an open, disclosed empirical question,
not an assumption. Step 3 checks this directly against real volume data
before Step 6's VWAP profile is built flat or curved.

## Impact parameter estimates (placeholder — finalized in Step 7)

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
   Almgren-Chriss implementation lands in Step 7, flagged explicitly as
   **equities-derived, applied to crypto as a disclosed cross-asset-class
   assumption.**
2. Separately estimate coefficients directly from this project's own
   reconstructed real order book (Step 7's empirical calibration), and
   compare the two — divergence between them is itself a result worth
   reporting, not just a calibration detail.

No numeric values are hardcoded yet; this section exists so Step 7 has a
documented starting point rather than an unstated assumption.

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
└── raw/                    # gitignored; populated by the two scripts above
```

## Usage

```
pip install -r requirements.txt
python3 -m data.fetch_depth
python3 -m data.fetch_volume --days 7 --interval 60
```
