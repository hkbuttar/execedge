"""Bokeh server app: execution trajectory per algorithm/calibration
source, comparison charts with confidence intervals, venue-routing
breakdown, and the cross-venue validation view. Every panel calls
straight into `frontend.data_access` (in-process, no separate backend
process needs to be running) and renders via `frontend.plots`.

Run with:

    bokeh serve frontend/app.py

then open the URL bokeh prints (default http://localhost:5006/app).

Not visually verified in this environment -- bokeh isn't installed here
(see frontend/README.md). The data-handling logic in each callback below
was checked by calling `frontend.data_access` directly against this
project's real recorded data before wiring it into these widgets; what's
unverified is Bokeh's own rendering of the resulting figures. Run it
yourself and see.
"""

import sys
from pathlib import Path

# `bokeh serve` puts only this file's own directory on sys.path, not the
# repo root -- add it so the sibling `frontend`/`backend` packages resolve
# regardless of the caller's cwd or PYTHONPATH.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from bokeh.io import curdoc
from bokeh.layouts import column, row
from bokeh.models import Button, Div, NumericInput, Select, TabPanel, Tabs, TextInput

from frontend import data_access, plots

DEFAULT_BOOK_HISTORY = "lob/raw/binance_book_snapshots.jsonl"
DEFAULT_REGIMES_CSV = "data/raw/regimes/binance_regimes.csv"


def _error_div(message: str) -> Div:
    return Div(text=f'<b style="color:#d62728">Error: {message}</b>')


def build_trajectory_section():
    book_history_input = TextInput(title="Book history path", value=DEFAULT_BOOK_HISTORY)
    side_select = Select(title="Side", value="buy", options=["buy", "sell"])
    quantity_input = NumericInput(title="Quantity", value=1.0, mode="float")
    n_slices_input = NumericInput(title="N slices", value=5, mode="int")
    duration_input = NumericInput(title="Duration (seconds)", value=300, mode="float")
    run_button = Button(label="Run: naive vs twap", button_type="primary")
    plot_area = column()

    def on_run():
        try:
            trajectories = {}
            for algorithm in ("naive", "twap"):
                result = data_access.get_trajectory(
                    book_history_path=book_history_input.value, side=side_select.value,
                    quantity=quantity_input.value, algorithm=algorithm,
                    n_slices=int(n_slices_input.value), duration_seconds=duration_input.value,
                    temporary_impact_coef=0.0, permanent_impact_coef=0.0,
                )
                trajectories[algorithm] = result["points"]
            plot_area.children = [plots.trajectory_figure(trajectories)]
        except Exception as exc:
            plot_area.children = [_error_div(str(exc))]

    run_button.on_click(on_run)
    controls = column(
        book_history_input, side_select, quantity_input, n_slices_input, duration_input, run_button
    )
    return row(controls, plot_area)


def build_comparison_section():
    book_history_input = TextInput(title="Book history path", value=DEFAULT_BOOK_HISTORY)
    side_select = Select(title="Side", value="buy", options=["buy", "sell"])
    quantity_input = NumericInput(title="Quantity", value=1.0, mode="float")
    n_slices_input = NumericInput(title="N slices", value=5, mode="int")
    episode_duration_input = NumericInput(title="Episode duration (s)", value=30, mode="float")
    stride_input = NumericInput(title="Stride (s)", value=30, mode="float")
    regimes_csv_input = TextInput(title="Regimes CSV (optional)", value=DEFAULT_REGIMES_CSV)
    regime_select = Select(title="Regime to display", value="all", options=["all"])
    run_button = Button(label="Run", button_type="primary")
    plot_area = column()
    state = {"results": None}

    def redraw():
        try:
            plot_area.children = [plots.comparison_figure(state["results"], regime=regime_select.value)]
        except Exception as exc:
            plot_area.children = [_error_div(str(exc))]

    def on_run():
        try:
            results = data_access.get_experiment(
                book_history_path=book_history_input.value, side=side_select.value,
                quantity=quantity_input.value, n_slices=int(n_slices_input.value),
                episode_duration_seconds=episode_duration_input.value, stride_seconds=stride_input.value,
                temporary_impact_coef=0.0, permanent_impact_coef=0.0,
                regimes_csv=regimes_csv_input.value or None,
            )
            state["results"] = results
            regimes = sorted({r["regime"] for r in results})
            regime_select.options = regimes
            if regime_select.value not in regimes:
                regime_select.value = regimes[0]
            redraw()
        except Exception as exc:
            plot_area.children = [_error_div(str(exc))]

    run_button.on_click(on_run)
    regime_select.on_change("value", lambda attr, old, new: redraw())
    controls = column(
        book_history_input, side_select, quantity_input, n_slices_input,
        episode_duration_input, stride_input, regimes_csv_input, regime_select, run_button,
    )
    return row(controls, plot_area)


def build_venue_routing_section():
    binance_input = TextInput(title="Binance book history", value="lob/raw/binance_book_snapshots.jsonl")
    coinbase_input = TextInput(title="Coinbase book history", value="lob/raw/coinbase_book_snapshots.jsonl")
    kraken_input = TextInput(title="Kraken book history", value="lob/raw/kraken_book_snapshots.jsonl")
    side_select = Select(title="Side", value="buy", options=["buy", "sell"])
    quantity_input = NumericInput(title="Quantity", value=1.0, mode="float")
    algorithm_select = Select(title="Algorithm", value="twap", options=["naive", "twap"])
    n_slices_input = NumericInput(title="N slices", value=10, mode="int")
    duration_input = NumericInput(title="Duration (seconds)", value=300, mode="float")
    run_button = Button(label="Run", button_type="primary")
    plot_area = column()

    def on_run():
        try:
            result = data_access.get_venue_routing_comparison(
                binance_book_history_path=binance_input.value,
                coinbase_book_history_path=coinbase_input.value,
                kraken_book_history_path=kraken_input.value,
                side=side_select.value, quantity=quantity_input.value,
                algorithm=algorithm_select.value, n_slices=int(n_slices_input.value),
                duration_seconds=duration_input.value,
                temporary_impact_coef=0.0, permanent_impact_coef=0.0,
            )
            plot_area.children = [plots.venue_routing_figure(result)]
        except Exception as exc:
            plot_area.children = [_error_div(str(exc))]

    run_button.on_click(on_run)
    controls = column(
        binance_input, coinbase_input, kraken_input, side_select, quantity_input,
        algorithm_select, n_slices_input, duration_input, run_button,
    )
    return row(controls, plot_area)


def build_cross_venue_section():
    binance_input = TextInput(title="Binance book history", value="lob/raw/binance_book_snapshots.jsonl")
    coinbase_input = TextInput(title="Coinbase book history", value="lob/raw/coinbase_book_snapshots.jsonl")
    kraken_input = TextInput(title="Kraken book history", value="lob/raw/kraken_book_snapshots.jsonl")
    side_select = Select(title="Side", value="buy", options=["buy", "sell"])
    quantity_input = NumericInput(title="Quantity", value=1.0, mode="float")
    n_slices_input = NumericInput(title="N slices", value=5, mode="int")
    episode_duration_input = NumericInput(title="Episode duration (s)", value=30, mode="float")
    stride_input = NumericInput(title="Stride (s)", value=30, mode="float")
    run_button = Button(label="Run", button_type="primary")
    plot_area = column()

    def on_run():
        try:
            result = data_access.get_cross_venue_validation(
                binance_book_history_path=binance_input.value,
                coinbase_book_history_path=coinbase_input.value,
                kraken_book_history_path=kraken_input.value,
                side=side_select.value, quantity=quantity_input.value,
                n_slices=int(n_slices_input.value),
                episode_duration_seconds=episode_duration_input.value, stride_seconds=stride_input.value,
                temporary_impact_coef=0.0, permanent_impact_coef=0.0,
            )
            plot_area.children = [plots.cross_venue_figure(result)]
        except Exception as exc:
            plot_area.children = [_error_div(str(exc))]

    run_button.on_click(on_run)
    controls = column(
        binance_input, coinbase_input, kraken_input, side_select, quantity_input,
        n_slices_input, episode_duration_input, stride_input, run_button,
    )
    return row(controls, plot_area)


tabs = Tabs(tabs=[
    TabPanel(child=build_trajectory_section(), title="Execution trajectory"),
    TabPanel(child=build_comparison_section(), title="Algorithm comparison"),
    TabPanel(child=build_venue_routing_section(), title="Venue routing"),
    TabPanel(child=build_cross_venue_section(), title="Cross-venue validation"),
])

curdoc().title = "ExecEdge"
curdoc().add_root(tabs)
