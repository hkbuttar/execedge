# ExecEdge — Optimal Execution Algorithm Backtester

Optimal execution backtester for large crypto orders, built entirely on
real order book data from Binance, Coinbase, and Kraken. TWAP, VWAP (real
volume profiles), Almgren-Chriss (literature-calibrated + empirically-
estimated impact), and an RL policy, benchmarked with statistical rigor.

## Status

Real-data acquisition, order book reconstruction, regime/time-of-day
analysis, the order-slicing simulator, TWAP/VWAP/Almgren-Chriss, an RL
execution policy, the risk layer, multi-venue routing, and the
bootstrap-based statistical comparison layer are all in place — see each
module's own README (`data/`, `lob/`, `backtest/`, `algos/`, `rl/`,
`risk/`, `venues/`) for details. No API keys are required anywhere in
this project. The backend/frontend/deployment layers are not yet built.

See `data/README.md` for the full data-source disclosure, including the
Binance.US substitution and the 24/7-trading / no-open-close-curve caveat.
