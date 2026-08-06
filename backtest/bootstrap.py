"""Bootstrap confidence intervals for implementation shortfall, computed
across many real historical windows (different real dates/sessions as
the source of variation -- Step 11's discipline, not a parametric
assumption about the shape of shortfall's distribution).
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class BootstrapResult:
    point_estimate: float  # sample mean of the observed per-window values
    ci_low: float
    ci_high: float
    n_samples: int  # number of real windows the estimate is based on
    n_resamples: int
    confidence_level: float

    @property
    def ci_width(self) -> float:
        return self.ci_high - self.ci_low


def bootstrap_mean_ci(
    values: list, n_resamples: int = 2000, confidence_level: float = 0.95, seed: int = None
) -> BootstrapResult:
    """Percentile bootstrap CI for the mean of `values` (one implementation-
    shortfall bps observation per real historical window). Resamples
    `values` with replacement `n_resamples` times, computes the mean of
    each resample, and takes the (alpha/2, 1-alpha/2) percentiles of that
    distribution as the CI bounds -- no assumption that per-window
    shortfall is normally distributed, which it has no particular reason
    to be.
    """
    if len(values) < 2:
        raise ValueError(
            f"need at least 2 real windows for a bootstrap CI, got {len(values)} -- "
            f"record a longer book history or use a shorter/overlapping window schedule "
            f"so more windows fit"
        )

    arr = np.asarray(values, dtype=float)
    n = len(arr)
    rng = np.random.default_rng(seed)

    resample_indices = rng.integers(0, n, size=(n_resamples, n))
    resampled_means = arr[resample_indices].mean(axis=1)

    alpha = 1 - confidence_level
    ci_low, ci_high = np.quantile(resampled_means, [alpha / 2, 1 - alpha / 2])

    return BootstrapResult(
        point_estimate=float(arr.mean()),
        ci_low=float(ci_low),
        ci_high=float(ci_high),
        n_samples=n,
        n_resamples=n_resamples,
        confidence_level=confidence_level,
    )
