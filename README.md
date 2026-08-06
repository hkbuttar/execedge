# ExecEdge — Optimal Execution Algorithm Backtester

Optimal execution backtester for large crypto orders, built entirely on
real order book data from Binance, Coinbase, and Kraken. TWAP, VWAP (real
volume profiles), Almgren-Chriss (literature-calibrated + empirically-
estimated impact), and an RL policy, benchmarked with statistical rigor.

## Status

Step 1 (environment + real-data acquisition) is in place: venue clients
for Binance, Coinbase, and Kraken's public depth and kline endpoints, with
coverage/convention differences documented in [data/README.md](data/README.md).
No API keys are required anywhere in this project.

See `data/README.md` for the full data-source disclosure, including the
Binance.US substitution and the 24/7-trading / no-open-close-curve caveat.
Remaining steps (order book reconstruction, algorithms, RL, backtesting,
backend/frontend) are not yet implemented.
