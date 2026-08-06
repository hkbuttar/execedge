"""Data layer for the Bokeh frontend: calls straight into
`backend.services` in-process (constructing the same Pydantic request
models `backend/main.py`'s HTTP routes use) rather than making HTTP
requests to a separately-running backend process. One process to run
locally or deploy, and the exact same validated request/response shapes
either way -- if the backend's routes and this data layer ever drift
apart, it'll show up as a signature mismatch immediately, not a subtle
behavioral difference between "the API" and "the app."

Every function here raises `ValueError` on bad input (missing file,
missing required calibration args, too little data) -- exactly what
`backend.services` raises, and what `frontend/app.py` catches to show as
an error message in the UI instead of crashing the server process.
"""

from backend import services
from backend.schemas import (
    BacktestRequest,
    CalibrationCompareRequest,
    CrossVenueRequest,
    ExperimentRequest,
    RLDiagnosticsRequest,
    VenueRoutingRequest,
)


def get_trajectory(**kwargs) -> dict:
    """See BacktestRequest for accepted fields (book_history_path, side,
    quantity, algorithm, n_slices, start_offset_seconds, duration_seconds,
    temporary_impact_coef, permanent_impact_coef, and the ac_* fields)."""
    return services.run_backtest_trajectory(BacktestRequest(**kwargs))


def get_backtest(**kwargs) -> dict:
    return services.run_backtest(BacktestRequest(**kwargs))


def get_experiment(**kwargs) -> list:
    return services.run_experiment(ExperimentRequest(**kwargs))


def get_calibration_comparison(**kwargs) -> dict:
    return services.compare_calibration(CalibrationCompareRequest(**kwargs))


def get_fee_schedules() -> list:
    return services.get_fee_schedules()


def get_cross_venue_validation(**kwargs) -> dict:
    return services.cross_venue_validate(CrossVenueRequest(**kwargs))


def get_venue_routing_comparison(**kwargs) -> dict:
    return services.run_venue_routing_comparison(VenueRoutingRequest(**kwargs))


def get_rl_diagnostics(**kwargs) -> dict:
    return services.get_rl_diagnostics(RLDiagnosticsRequest(**kwargs))
