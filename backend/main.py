"""FastAPI backend: serves backtest, calibration, and training results as
JSON. Every route is a thin wrapper around backend/services.py, which
itself only composes already-tested logic from backtest/, algos/,
venues/, and rl/ -- this layer adds no new statistics or execution
mechanics of its own.

Deliberately only exposes fast, synchronous operations: a single
backtest, a bootstrap experiment over already-recorded windows, a
calibration comparison, a cross-venue ranking check, fee schedules, and
reading an existing training-reward log. Long-running/blocking
operations -- recording a live book (`lob.run_reconstruction`), training
an RL policy (`rl.train`) -- are deliberately NOT exposed here: an HTTP
request that blocks for however long a websocket connection or a
training run takes is the wrong shape for a request/response API. Run
those yourself from the CLI as documented in each module's README, then
use this backend to serve/query the results.

    uvicorn backend.main:app --reload
"""

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from backend import services
from backend.schemas import (
    BacktestRequest,
    BacktestResponse,
    CalibrationCompareRequest,
    CalibrationCompareResponse,
    CrossVenueRequest,
    CrossVenueResponse,
    ExperimentRequest,
    FeeScheduleOut,
    RLDiagnosticsRequest,
    RLDiagnosticsResponse,
    ScenarioResultOut,
)

app = FastAPI(
    title="ExecEdge backend",
    description="Serves backtest, calibration, and training results as JSON.",
)


def _run_or_400(fn, req):
    try:
        return fn(req)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/backtest", response_model=BacktestResponse)
def backtest(req: BacktestRequest):
    return _run_or_400(services.run_backtest, req)


@app.post("/experiment", response_model=list[ScenarioResultOut])
def experiment(req: ExperimentRequest):
    return _run_or_400(services.run_experiment, req)


@app.post("/calibration/compare", response_model=CalibrationCompareResponse)
def calibration_compare(req: CalibrationCompareRequest):
    return _run_or_400(services.compare_calibration, req)


@app.get("/venues/fees", response_model=list[FeeScheduleOut])
def venues_fees():
    return services.get_fee_schedules()


@app.post("/venues/cross-validate", response_model=CrossVenueResponse)
def venues_cross_validate(req: CrossVenueRequest):
    return _run_or_400(services.cross_venue_validate, req)


@app.post("/rl/diagnostics", response_model=RLDiagnosticsResponse)
def rl_diagnostics(req: RLDiagnosticsRequest):
    return _run_or_400(services.get_rl_diagnostics, req)


@app.get("/results", response_class=PlainTextResponse)
def results():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "RESULTS.md")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="RESULTS.md not found")
    with open(path) as f:
        return f.read()
