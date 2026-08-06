"""Pydantic request/response models for the backend. Serves backtest,
calibration, and training results as JSON -- every endpoint here is a
thin adapter over already-built, already-tested logic in backtest/,
algos/, venues/, and rl/. Nothing is recomputed or reimplemented here.
"""

from typing import Optional

from pydantic import BaseModel


class BacktestRequest(BaseModel):
    book_history_path: str
    side: str  # "buy" | "sell"
    quantity: float
    algorithm: str = "twap"  # naive | twap | vwap | ac
    n_slices: int = 10
    start_offset_seconds: float = 0.0
    duration_seconds: float
    temporary_impact_coef: float
    permanent_impact_coef: float
    volume_csv: Optional[str] = None
    time_of_day_alpha: float = 0.05
    ac_calibration: Optional[str] = None  # "literature" | "empirical"
    ac_volatility: Optional[float] = None
    ac_risk_aversion: Optional[float] = None
    ac_permanent_to_temporary_ratio: Optional[float] = None
    ac_sqrt_law_coefficient: Optional[float] = None
    ac_reference_participation_rate: Optional[float] = None
    ac_empirical_order_sizes: Optional[str] = None


class BacktestResponse(BaseModel):
    venue: str
    symbol: str
    side: str
    quantity: float
    algorithm: str
    arrival_price: float
    end_price: float
    n_child_orders: int
    n_fills: int
    executed_quantity: float
    unfilled_quantity: float
    executed_cost: float
    opportunity_cost: float
    total_cost: float
    total_cost_bps: float


class ExperimentRequest(BaseModel):
    book_history_path: str
    side: str
    quantity: float
    n_slices: int = 10
    episode_duration_seconds: float
    stride_seconds: float
    temporary_impact_coef: float
    permanent_impact_coef: float
    regimes_csv: Optional[str] = None
    volume_csv: Optional[str] = None
    time_of_day_alpha: float = 0.05
    ac_volatility: Optional[float] = None
    ac_risk_aversion: Optional[float] = None
    ac_permanent_to_temporary_ratio: Optional[float] = None
    ac_sqrt_law_coefficient: Optional[float] = None
    ac_reference_participation_rate: Optional[float] = None
    ac_empirical_order_sizes: Optional[str] = None
    n_resamples: int = 2000
    confidence_level: float = 0.95
    seed: Optional[int] = None


class ScenarioResultOut(BaseModel):
    scenario: str
    regime: str
    n_samples: int
    mean_bps: float
    ci_low: float
    ci_high: float
    robust: bool


class CalibrationCompareRequest(BaseModel):
    book_history_path: str
    side: str
    ac_volatility: float
    ac_risk_aversion: float
    ac_permanent_to_temporary_ratio: float
    ac_sqrt_law_coefficient: float
    ac_reference_participation_rate: float
    ac_empirical_order_sizes: str


class CalibrationCompareResponse(BaseModel):
    venue: str
    symbol: str
    temporary_impact_literature: float
    temporary_impact_empirical: float
    temporary_impact_ratio: float
    permanent_impact_literature: float
    permanent_impact_empirical: float
    permanent_impact_ratio: float
    empirical_n_samples: int
    empirical_r_squared: float


class FeeScheduleOut(BaseModel):
    venue: str
    maker_fee_bps: float
    taker_fee_bps: float
    source: str


class CrossVenueRequest(BaseModel):
    binance_book_history_path: str
    coinbase_book_history_path: str
    kraken_book_history_path: str
    side: str
    quantity: float
    n_slices: int = 10
    episode_duration_seconds: float
    stride_seconds: float
    temporary_impact_coef: float
    permanent_impact_coef: float
    regime: str = "all"
    n_resamples: int = 2000
    confidence_level: float = 0.95
    seed: Optional[int] = None


class VenueRankingOut(BaseModel):
    ranking: list
    means: dict
    robust: dict


class CrossVenueResponse(BaseModel):
    regime: str
    rankings: dict[str, VenueRankingOut]
    common_scenarios: list
    consistent: bool
    common_ranking: list
    divergences: list


class RLDiagnosticsRequest(BaseModel):
    rewards_csv: str
    window_fraction: float = 0.2


class RLDiagnosticsResponse(BaseModel):
    n_episodes: int
    mean_reward: float
    std_reward: float
    min_reward: float
    max_reward: float
    early_mean_reward: float
    late_mean_reward: float
    improved: bool
    has_nan_or_inf: bool
