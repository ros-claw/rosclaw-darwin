"""Unit tests for rosclaw_darwin.analysis.statistics."""

from __future__ import annotations

import math

import pytest

from rosclaw_darwin.analysis.statistics import (
    bootstrap_ci,
    bootstrap_delta_ci,
    effect_size_absolute_delta,
    fisher_exact_test,
    summarize_binary_condition,
    summarize_continuous_condition,
    two_proportion_z_test,
    wilson_ci,
)


def test_wilson_ci_bounds():
    lower, upper = wilson_ci(5, 10)
    assert 0.0 <= lower <= upper <= 1.0
    # With 5/10 the interval should straddle 0.5.
    assert lower < 0.5 < upper


def test_wilson_ci_full_success():
    lower, upper = wilson_ci(10, 10)
    assert lower > 0.5 and upper == 1.0


def test_wilson_ci_empty():
    lower, upper = wilson_ci(0, 0)
    assert (lower, upper) == (0.0, 0.0)


def test_bootstrap_ci_reasonable():
    values = [0.4, 0.5, 0.6, 0.55, 0.45, 0.52, 0.48, 0.58]
    lower, upper = bootstrap_ci(values, n_boot=2000, seed=0)
    assert lower < upper
    assert lower <= math.fsum(values) / len(values) <= upper


def test_bootstrap_ci_empty():
    lower, upper = bootstrap_ci([])
    assert math.isnan(lower) and math.isnan(upper)


def test_bootstrap_delta_ci():
    a = [0.4] * 20
    b = [0.5] * 20
    lower, upper = bootstrap_delta_ci(a, b, n_boot=2000, seed=0)
    # Mean difference is 0.1; CI should contain it (allow fp tolerance).
    assert lower <= 0.1 + 1e-9
    assert 0.1 - 1e-9 <= upper


def test_two_proportion_z_test_basic():
    result = two_proportion_z_test(40, 100, 50, 100)
    assert result["p_a"] == 0.4
    assert result["p_b"] == 0.5
    assert result["delta"] == 0.1
    assert result["z_score"] is not None
    assert 0.0 < result["p_value"] <= 1.0


def test_two_proportion_z_test_no_data():
    result = two_proportion_z_test(0, 0, 0, 0)
    assert result["z_score"] is None


def test_fisher_exact_test_basic():
    result = fisher_exact_test(1, 9, 8, 2)
    assert "odds_ratio" in result
    assert "p_value" in result
    assert 0.0 < result["p_value"] <= 1.0
    assert result["table"] == [[1, 8], [9, 2]]


def test_fisher_exact_test_large_table():
    # Large balanced table should trigger chi-square approximation.
    result = fisher_exact_test(45, 55, 50, 50)
    assert result["method"] == "chi_square_approximation"
    assert result["p_value"] > 0.3  # roughly non-significant


def test_effect_size_absolute_delta():
    assert effect_size_absolute_delta(0.44, 0.54) == pytest.approx(0.10)


def test_summarize_binary_condition():
    successes = [True, False, True, True, False]
    summary = summarize_binary_condition(successes)
    assert summary["n_success"] == 3
    assert summary["n_total"] == 5
    assert summary["rate"] == 0.6
    assert summary["ci_lower"] < summary["ci_upper"]


def test_summarize_continuous_condition():
    values = [0.1, 0.2, 0.3, 0.4, 0.5]
    summary = summarize_continuous_condition(values)
    assert summary["mean"] == pytest.approx(0.3)
    assert summary["median"] == pytest.approx(0.3)
    assert summary["n"] == 5
    assert summary["ci_lower"] < summary["ci_upper"]


def test_summarize_continuous_condition_empty():
    summary = summarize_continuous_condition([])
    assert math.isnan(summary["mean"])
    assert summary["n"] == 0
