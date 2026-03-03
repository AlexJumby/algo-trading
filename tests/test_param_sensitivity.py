"""Tests for parameter sensitivity analysis utilities."""
import pytest

from scripts.param_sensitivity import apply_shift, classify_robustness


class TestApplyShift:
    def test_zero_shift(self):
        assert apply_shift(100, 0.0, "int") == 100
        assert apply_shift(0.5, 0.0, "float") == 0.5

    def test_positive_shift_int(self):
        assert apply_shift(100, 0.20, "int") == 120

    def test_negative_shift_int(self):
        assert apply_shift(100, -0.20, "int") == 80

    def test_float_shift(self):
        result = apply_shift(0.5, 0.10, "float")
        assert abs(result - 0.55) < 1e-6

    def test_int_minimum_1(self):
        """Integer params should never go below 1."""
        assert apply_shift(1, -0.90, "int") == 1


class TestClassifyRobustness:
    def test_robust(self):
        """All Sharpes above 80% of base → ROBUST."""
        sharpes = [0.9, 0.95, 1.0, 0.95, 0.9]
        assert classify_robustness(sharpes, 1.0) == "ROBUST"

    def test_fragile_negative(self):
        """Any negative Sharpe → FRAGILE."""
        sharpes = [0.8, 0.9, 1.0, -0.1, 0.5]
        assert classify_robustness(sharpes, 1.0) == "FRAGILE"

    def test_fragile_below_half(self):
        """Min Sharpe < 0.5 → FRAGILE."""
        sharpes = [0.4, 0.9, 1.0, 0.9, 0.8]
        assert classify_robustness(sharpes, 1.0) == "FRAGILE"

    def test_moderate(self):
        """Between robust and fragile → MODERATE."""
        sharpes = [0.6, 0.8, 1.0, 0.8, 0.7]
        assert classify_robustness(sharpes, 1.0) == "MODERATE"

    def test_zero_base_sharpe(self):
        """Zero base Sharpe → FRAGILE."""
        assert classify_robustness([0, 0, 0], 0.0) == "FRAGILE"
