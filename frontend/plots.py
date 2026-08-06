"""Bokeh figure-building functions: each takes the plain dict/list data
that `frontend/data_access.py` returns (the same shapes `backend/main.py`
serves as JSON) and returns a Bokeh figure. Pure functions, no I/O, no
Bokeh server/document state -- `frontend/app.py` is the only place that
wires these into a running server.

Not executable-verified in this environment (bokeh isn't installed here
-- see frontend/README.md); written carefully against Bokeh's stable,
documented plotting API, but genuinely unverified visually. Run
`bokeh serve frontend/app.py` yourself to confirm these render as
intended.
"""

from datetime import datetime

from bokeh.models import ColumnDataSource, FactorRange, Whisker
from bokeh.palettes import Category10
from bokeh.plotting import figure
from bokeh.transform import factor_cmap

ROBUST_COLOR = "#2ca02c"
FRAGILE_COLOR = "#d62728"


def _palette(n: int) -> list:
    """Category10 needs at least 3 colors; slice down for fewer series."""
    base = Category10[10]
    return base[:n] if n <= len(base) else base * (n // len(base) + 1)


def trajectory_figure(trajectories: dict, title: str = "Execution trajectory") -> figure:
    """`trajectories` is {label: points}, where each `points` is a
    TrajectoryResponse["points"] list -- one line per algorithm/
    calibration source, so they can be compared on the same axes."""
    p = figure(
        title=title, x_axis_type="datetime", height=400, width=700,
        x_axis_label="time", y_axis_label="remaining quantity",
        tools="pan,wheel_zoom,box_zoom,reset,save",
    )

    colors = _palette(len(trajectories))
    for color, (label, points) in zip(colors, trajectories.items()):
        timestamps = [datetime.fromisoformat(pt["timestamp"]) for pt in points]
        remaining = [pt["remaining_quantity"] for pt in points]
        source = ColumnDataSource(data={"x": timestamps, "y": remaining})
        p.line(x="x", y="y", source=source, legend_label=label, color=color, line_width=2)
        p.scatter(x="x", y="y", source=source, color=color, size=6, marker="circle")

    p.legend.location = "top_right"
    p.legend.click_policy = "hide"  # click a legend entry to hide/show that algorithm's line
    return p


def comparison_figure(scenario_results: list, regime: str = "all", title: str = None) -> figure:
    """Bar chart of mean implementation shortfall (bps) per algorithm
    scenario, for one regime, with whiskers showing the bootstrap CI and
    color flagging robust (tight CI) vs. fragile (wide CI, per
    backtest.experiment.is_robust) -- treat fragile bars' conclusions
    with real caution, not just their magnitude."""
    rows = [r for r in scenario_results if r["regime"] == regime]
    if not rows:
        raise ValueError(f"no scenario results for regime={regime!r}")
    rows = sorted(rows, key=lambda r: r["mean_bps"])

    scenarios = [r["scenario"] for r in rows]
    source = ColumnDataSource(data={
        "scenario": scenarios,
        "mean": [r["mean_bps"] for r in rows],
        "ci_low": [r["ci_low"] for r in rows],
        "ci_high": [r["ci_high"] for r in rows],
        "robustness": ["robust" if r["robust"] else "fragile" for r in rows],
    })

    p = figure(
        x_range=scenarios,
        title=title or f"Implementation shortfall by algorithm (regime={regime})",
        y_axis_label="mean shortfall (bps)", height=400, width=700,
        tools="pan,wheel_zoom,box_zoom,reset,save",
    )
    p.vbar(
        x="scenario", top="mean", width=0.6, source=source,
        fill_color=factor_cmap("robustness", palette=[ROBUST_COLOR, FRAGILE_COLOR], factors=["robust", "fragile"]),
        legend_field="robustness",
    )
    p.add_layout(Whisker(source=source, base="scenario", upper="ci_high", lower="ci_low"))
    p.xgrid.grid_line_color = None
    p.legend.location = "top_left"
    return p


def venue_routing_figure(routing_response: dict, title: str = None) -> figure:
    """Bar chart of shortfall (bps) per routing strategy
    (always_binance/always_coinbase/always_kraken/best_price) -- Step 10's
    "does smart routing meaningfully reduce cost" comparison. A single
    real window per strategy, not bootstrapped (matches
    venues.run_multi_venue_backtest exactly)."""
    strategies = routing_response["strategies"]
    names = [s["strategy"] for s in strategies]
    costs = [s["total_cost_bps"] for s in strategies]
    highlight = ["best_price" if s["strategy"] == "best_price" else "single_venue" for s in strategies]

    source = ColumnDataSource(data={"strategy": names, "cost_bps": costs, "highlight": highlight})

    improves = routing_response["smart_routing_improves"]
    default_title = (
        f"Venue routing ({routing_response['algorithm']}) — "
        f"smart routing {'improves' if improves else 'does NOT improve'} on best single venue"
    )
    p = figure(
        x_range=names, title=title or default_title,
        y_axis_label="shortfall (bps)", height=400, width=700,
        tools="pan,wheel_zoom,box_zoom,reset,save",
    )
    p.vbar(
        x="strategy", top="cost_bps", width=0.6, source=source,
        fill_color=factor_cmap("highlight", palette=["#1f77b4", "#ff7f0e"], factors=["single_venue", "best_price"]),
    )
    p.xgrid.grid_line_color = None
    return p


def cross_venue_figure(cross_venue_response: dict, title: str = None) -> figure:
    """Grouped bar chart: mean shortfall (bps) per (scenario, venue),
    restricted to scenarios common to every venue -- the same comparison
    `venues.run_cross_venue_validation` prints as a table, here as a
    nested-categorical bar chart so a diverging ranking is visible at a
    glance rather than read off numbers."""
    scenarios = cross_venue_response["common_scenarios"]
    venues = list(cross_venue_response["rankings"])
    if not scenarios or not venues:
        raise ValueError("no common scenarios/venues to plot")

    x = [(scenario, venue) for scenario in scenarios for venue in venues]
    means = [cross_venue_response["rankings"][venue]["means"].get(scenario, 0.0) for scenario, venue in x]
    source = ColumnDataSource(data={"x": x, "means": means, "venue": [venue for _, venue in x]})

    consistency = "CONSISTENT" if cross_venue_response["consistent"] else "DIVERGES"
    default_title = f"Cross-venue ranking ({cross_venue_response['regime']}) — {consistency}"

    p = figure(
        x_range=FactorRange(*x), title=title or default_title,
        y_axis_label="mean shortfall (bps)", height=450, width=900,
        tools="pan,wheel_zoom,box_zoom,reset,save",
    )
    p.vbar(
        x="x", top="means", width=0.9, source=source,
        fill_color=factor_cmap("venue", palette=_palette(len(venues)), factors=venues),
        line_color="white",
    )
    p.xaxis.major_label_orientation = 1
    p.xgrid.grid_line_color = None
    return p
