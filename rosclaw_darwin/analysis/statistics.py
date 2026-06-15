"""Statistical utilities for Arena evaluation results.

Provides bootstrap confidence intervals, proportion tests, effect-size
estimates, and compact summaries for both binary and continuous metrics.
"""

from __future__ import annotations

import math
import random
from typing import Any

import numpy as np


def _rng(seed: int | None = None) -> random.Random:
    """Return a deterministic random generator."""
    return random.Random(seed)


def bootstrap_ci(
    values: list[float],
    n_boot: int = 10000,
    alpha: float = 0.05,
    seed: int | None = 42,
) -> tuple[float, float]:
    """Bootstrap percentile CI for the mean of ``values``.

    Returns ``(lower, upper)``.  Empty input yields ``(nan, nan)``.
    """
    if not values:
        return float("nan"), float("nan")

    arr = np.asarray(values, dtype=float)
    rng = _rng(seed)
    n = len(arr)
    means: list[float] = []
    for _ in range(n_boot):
        sample = rng.choices(arr, k=n)
        means.append(float(np.mean(sample)))
    means_arr = np.asarray(means)
    lower = float(np.percentile(means_arr, 100 * alpha / 2))
    upper = float(np.percentile(means_arr, 100 * (1 - alpha / 2)))
    return lower, upper


def bootstrap_delta_ci(
    a: list[float],
    b: list[float],
    n_boot: int = 10000,
    alpha: float = 0.05,
    seed: int | None = 42,
) -> tuple[float, float]:
    """Bootstrap percentile CI for ``mean(b) - mean(a)``.

    Empty input yields ``(nan, nan)``.
    """
    if not a or not b:
        return float("nan"), float("nan")

    arr_a = np.asarray(a, dtype=float)
    arr_b = np.asarray(b, dtype=float)
    rng = _rng(seed)
    n_a, n_b = len(arr_a), len(arr_b)
    diffs: list[float] = []
    for _ in range(n_boot):
        sample_a = rng.choices(arr_a, k=n_a)
        sample_b = rng.choices(arr_b, k=n_b)
        diffs.append(float(np.mean(sample_b)) - float(np.mean(sample_a)))
    diffs_arr = np.asarray(diffs)
    lower = float(np.percentile(diffs_arr, 100 * alpha / 2))
    upper = float(np.percentile(diffs_arr, 100 * (1 - alpha / 2)))
    return lower, upper


def wilson_ci(
    successes: int,
    n: int,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Returns ``(lower, upper)``.  ``n <= 0`` yields ``(0.0, 0.0)``.
    """
    if n <= 0:
        return 0.0, 0.0
    if successes < 0:
        successes = 0
    if successes > n:
        successes = n

    z = _z_alpha(alpha)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half_width = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


def _z_alpha(alpha: float) -> float:
    """Two-sided normal quantile for confidence level ``1 - alpha``.

    Uses a rational approximation (Abramowitz & Stegun 26.2.17).
    """
    p = 1 - alpha / 2
    if p <= 0 or p >= 1:
        return 1.96
    if p < 0.5:
        p = 1 - p
    t = math.sqrt(-2 * math.log(1 - p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    num = c0 + c1 * t + c2 * t * t
    denom = 1 + d1 * t + d2 * t * t + d3 * t * t * t
    return t - num / denom


def two_proportion_z_test(
    success_a: int,
    n_a: int,
    success_b: int,
    n_b: int,
) -> dict[str, Any]:
    """Two-proportion z-test for ``p_b - p_a``.

    Returns a dict with ``z_score``, ``p_value`` (two-sided), ``p_a``,
    ``p_b``, ``delta``, and Wilson 95% CIs for each proportion.
    """
    success_a = max(0, min(success_a, n_a))
    success_b = max(0, min(success_b, n_b))
    if n_a <= 0 or n_b <= 0:
        return {
            "z_score": None,
            "p_value": None,
            "p_a": None,
            "p_b": None,
            "delta": None,
            "ci_a": (float("nan"), float("nan")),
            "ci_b": (float("nan"), float("nan")),
        }

    p_a = success_a / n_a
    p_b = success_b / n_b
    p_pooled = (success_a + success_b) / (n_a + n_b)
    se = math.sqrt(p_pooled * (1 - p_pooled) * (1 / n_a + 1 / n_b))
    delta = p_b - p_a
    z = delta / se if se > 0 else 0.0
    p_value = 2 * (1 - _normal_cdf(abs(z)))

    return {
        "z_score": round(z, 4),
        "p_value": round(p_value, 6),
        "p_a": round(p_a, 4),
        "p_b": round(p_b, 4),
        "delta": round(delta, 4),
        "ci_a": wilson_ci(success_a, n_a),
        "ci_b": wilson_ci(success_b, n_b),
    }


def _normal_cdf(x: float) -> float:
    """Standard normal CDF using a polynomial approximation."""
    if x < 0:
        return 1 - _normal_cdf(-x)
    b1, b2, b3 = 0.319381530, -0.356563782, 1.781477937
    b4, b5 = -1.821255978, 1.330274429
    p = 0.2316419
    t = 1 / (1 + p * x)
    poly = t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))
    return 1 - _phi(x) * poly


def _phi(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _log_factorial(n: int) -> float:
    """Log factorial using Stirling with a small-n correction."""
    if n < 0:
        return 0.0
    if n < 10:
        return math.log(math.factorial(n)) if n > 0 else 0.0
    return n * math.log(n) - n + 0.5 * math.log(2 * math.pi * n) + 1 / (12 * n)


def fisher_exact_test(
    success_a: int,
    fail_a: int,
    success_b: int,
    fail_b: int,
) -> dict[str, Any]:
    """Fisher's exact test for a 2x2 contingency table.

    Table layout::

                group A   group B
        success   a         b
        failure   c         d

    Returns ``odds_ratio``, ``p_value`` (two-sided), and the four cell
    counts.  For large tables the exact p-value is expensive, so we fall
    back to the chi-square approximation when any expected cell count is
    >= 5 and the total exceeds 100.
    """
    a = max(0, success_a)
    c = max(0, fail_a)
    b = max(0, success_b)
    d = max(0, fail_b)

    n = a + b + c + d
    if n == 0:
        return {"odds_ratio": None, "p_value": None, "table": [[0, 0], [0, 0]]}

    # Odds ratio with Haldane-Anscombe correction.
    odds_ratio = ((a + 0.5) * (d + 0.5)) / ((b + 0.5) * (c + 0.5)) if (b + 0.5) * (c + 0.5) > 0 else float("inf")

    # Use chi-square approximation for large tables to avoid combinatorial blow-up.
    expected = [
        (a + b) * (a + c) / n,
        (a + b) * (b + d) / n,
        (c + d) * (a + c) / n,
        (c + d) * (b + d) / n,
    ]
    if n > 100 and all(e >= 5 for e in expected):
        chi2 = sum((max(x, 0) - e) ** 2 / e for x, e in zip([a, b, c, d], expected) if e > 0)
        p_value = max(0.0, math.erfc(math.sqrt(chi2 / 2)))
        return {
            "odds_ratio": round(odds_ratio, 4),
            "p_value": round(p_value, 6),
            "method": "chi_square_approximation",
            "table": [[a, b], [c, d]],
        }

    # Exact two-sided p-value via the hypergeometric probability mass.
    log_p_obs = (
        _log_factorial(a + b)
        + _log_factorial(c + d)
        + _log_factorial(a + c)
        + _log_factorial(b + d)
        - _log_factorial(a)
        - _log_factorial(b)
        - _log_factorial(c)
        - _log_factorial(d)
        - _log_factorial(n)
    )
    p_obs = math.exp(log_p_obs)

    p_value = 0.0
    max_a = min(a + b, a + c)
    for k in range(max_a + 1):
        if k > a + b or (a + c - k) < 0 or (a + b - k) < 0 or (c + d - a - c + k) < 0:
            continue
        log_p_k = (
            _log_factorial(a + b)
            + _log_factorial(c + d)
            + _log_factorial(a + c)
            + _log_factorial(b + d)
            - _log_factorial(k)
            - _log_factorial(a + b - k)
            - _log_factorial(a + c - k)
            - _log_factorial(b + d - a - c + k)
            - _log_factorial(n)
        )
        p_k = math.exp(log_p_k)
        if p_k <= p_obs * (1 + 1e-12):
            p_value += p_k

    p_value = min(1.0, p_value)
    return {
        "odds_ratio": round(odds_ratio, 4),
        "p_value": round(p_value, 6),
        "method": "fisher_exact",
        "table": [[a, b], [c, d]],
    }


def effect_size_absolute_delta(rate_a: float, rate_b: float) -> float:
    """Absolute difference between two rates."""
    return round(float(rate_b) - float(rate_a), 4)


def summarize_binary_condition(successes: list[bool]) -> dict[str, Any]:
    """Summary statistics for a binary outcome.

    Returns count, total, rate, Wilson 95% CI, and an estimate of the
    standard error.
    """
    total = len(successes)
    n_success = sum(1 for s in successes if s)
    rate = n_success / total if total > 0 else 0.0
    ci_lower, ci_upper = wilson_ci(n_success, total)
    se = math.sqrt(rate * (1 - rate) / total) if total > 0 else 0.0
    return {
        "n_success": n_success,
        "n_total": total,
        "rate": round(rate, 4),
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "se": round(se, 4),
    }


def summarize_continuous_condition(values: list[float]) -> dict[str, Any]:
    """Summary statistics for a continuous outcome.

    Returns mean, median, std, min, max, and bootstrap 95% CI for the mean.
    """
    if not values:
        return {
            "mean": float("nan"),
            "median": float("nan"),
            "std": float("nan"),
            "min": float("nan"),
            "max": float("nan"),
            "ci_lower": float("nan"),
            "ci_upper": float("nan"),
            "n": 0,
        }
    arr = np.asarray(values, dtype=float)
    ci_lower, ci_upper = bootstrap_ci(values)
    return {
        "mean": round(float(np.mean(arr)), 6),
        "median": round(float(np.median(arr)), 6),
        "std": round(float(np.std(arr, ddof=1)), 6),
        "min": round(float(np.min(arr)), 6),
        "max": round(float(np.max(arr)), 6),
        "ci_lower": round(ci_lower, 6),
        "ci_upper": round(ci_upper, 6),
        "n": len(arr),
    }
