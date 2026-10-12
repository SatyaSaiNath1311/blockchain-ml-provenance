"""Statistical helpers for evaluation experiments.

Provides Wilson score confidence intervals for binomial metrics (detection rates, FPR)
and Student's t-confidence intervals for continuous variables (latencies, storage sizes).
"""

from typing import Any
import numpy as np
import scipy.stats


def wilson_score_interval(
    successes: int,
    trials: int,
    confidence: float = 0.95,
) -> tuple[float, float, float]:
    """Calculate the Wilson score interval for a binomial proportion.

    Returns:
        tuple of (point_estimate, lower_bound, upper_bound)
    """
    if trials <= 0:
        return 0.0, 0.0, 1.0

    p_hat = successes / trials
    z = float(scipy.stats.norm.ppf(1.0 - (1.0 - confidence) / 2.0))
    z2 = z * z

    denominator = 1.0 + z2 / trials
    center = (p_hat + z2 / (2.0 * trials)) / denominator
    spread = (z / denominator) * np.sqrt(
        (p_hat * (1.0 - p_hat) / trials) + (z2 / (4.0 * trials * trials))
    )

    lower = max(0.0, float(center - spread))
    upper = min(1.0, float(center + spread))
    if successes == trials:
        upper = 1.0
    if successes == 0:
        lower = 0.0
    return float(p_hat), lower, upper


def t_interval(
    values: list[float] | np.ndarray,
    confidence: float = 0.95,
) -> tuple[float, float, float]:
    """Calculate Student's t-interval for continuous metrics.

    Returns:
        tuple of (mean, lower_bound, upper_bound)
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    if n == 0:
        return 0.0, 0.0, 0.0
    mean = float(np.mean(arr))
    if n < 2:
        return mean, mean, mean

    sem = float(scipy.stats.sem(arr))
    if sem == 0.0:
        return mean, mean, mean

    ci = scipy.stats.t.interval(confidence, df=n - 1, loc=mean, scale=sem)
    return mean, float(ci[0]), float(ci[1])


def summary_stats(
    values: list[float] | np.ndarray,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Compute comprehensive descriptive statistics and 95% t-interval."""
    arr = np.asarray(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    if n == 0:
        return {
            "n": 0,
            "mean": 0.0,
            "std": 0.0,
            "median": 0.0,
            "min": 0.0,
            "max": 0.0,
            "ci_lower": 0.0,
            "ci_upper": 0.0,
        }

    mean, lower, upper = t_interval(arr, confidence=confidence)
    std = float(np.std(arr, ddof=1)) if n > 1 else 0.0
    median = float(np.median(arr))
    min_val = float(np.min(arr))
    max_val = float(np.max(arr))

    return {
        "n": n,
        "mean": mean,
        "std": std,
        "median": median,
        "min": min_val,
        "max": max_val,
        "ci_lower": lower,
        "ci_upper": upper,
    }
