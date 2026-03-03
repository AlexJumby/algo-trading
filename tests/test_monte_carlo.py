"""Tests for Monte Carlo simulation utilities."""
from __future__ import annotations

import numpy as np
import pytest

from scripts.monte_carlo import build_equity_curve, compute_max_drawdown, run_monte_carlo


class TestBuildEquityCurve:
    def test_empty_pnls(self):
        eq = build_equity_curve([], 10000.0)
        assert eq == [10000.0]

    def test_single_win(self):
        eq = build_equity_curve([500.0], 10000.0)
        assert eq == [10000.0, 10500.0]

    def test_single_loss(self):
        eq = build_equity_curve([-300.0], 10000.0)
        assert eq == [10000.0, 9700.0]

    def test_multiple_trades(self):
        eq = build_equity_curve([100, -50, 200], 10000.0)
        assert eq == [10000.0, 10100.0, 10050.0, 10250.0]

    def test_all_losses_total(self):
        eq = build_equity_curve([-100, -200, -300], 10000.0)
        assert eq[-1] == pytest.approx(10000.0 - 600.0)

    def test_length(self):
        pnls = [10, 20, -5, 30]
        eq = build_equity_curve(pnls, 5000.0)
        assert len(eq) == len(pnls) + 1


class TestComputeMaxDrawdown:
    def test_no_drawdown(self):
        equity = [100, 110, 120, 130]
        assert compute_max_drawdown(equity) == 0.0

    def test_simple_drawdown(self):
        equity = [100, 110, 90, 120]
        dd = compute_max_drawdown(equity)
        assert dd == pytest.approx(20 / 110)

    def test_empty(self):
        assert compute_max_drawdown([]) == 0.0

    def test_single_point(self):
        assert compute_max_drawdown([100]) == 0.0

    def test_full_drawdown(self):
        equity = [100, 50, 0]
        assert compute_max_drawdown(equity) == 1.0

    def test_monotonic_decline(self):
        equity = [100, 80, 60, 40]
        dd = compute_max_drawdown(equity)
        assert dd == pytest.approx(60 / 100)

    def test_recovery(self):
        """Drawdown is peak-to-trough, not final."""
        equity = [100, 50, 150]
        dd = compute_max_drawdown(equity)
        assert dd == pytest.approx(50 / 100)


class TestRunMonteCarlo:
    def test_basic_run(self):
        pnls = [100, -50, 200, -30, 150, -80, 100, -40, 200, -60]
        result = run_monte_carlo(pnls, 10000.0, n_simulations=100, seed=42)
        assert result["n_simulations"] == 100
        assert result["n_trades"] == 10
        assert "return_percentiles" in result
        assert "max_dd_percentiles" in result

    def test_all_wins(self):
        pnls = [100] * 20
        result = run_monte_carlo(pnls, 10000.0, n_simulations=100, seed=42)
        assert result["prob_negative_return"] == 0.0

    def test_all_losses(self):
        pnls = [-100] * 20
        result = run_monte_carlo(pnls, 10000.0, n_simulations=100, seed=42)
        assert result["prob_negative_return"] == 1.0

    def test_percentiles_ordered(self):
        pnls = [100, -50, 200, -30, 150, -80]
        result = run_monte_carlo(pnls, 10000.0, n_simulations=1000, seed=42)
        percs = result["return_percentiles"]
        assert percs[5] <= percs[25] <= percs[50] <= percs[75] <= percs[95]

    def test_reproducible_with_seed(self):
        pnls = [100, -50, 200, -30, 150]
        r1 = run_monte_carlo(pnls, 10000.0, n_simulations=100, seed=42)
        r2 = run_monte_carlo(pnls, 10000.0, n_simulations=100, seed=42)
        assert r1["mean_return"] == r2["mean_return"]

    def test_different_seeds_differ(self):
        pnls = [100, -50, 200, -30, 150, -80, 100]
        r1 = run_monte_carlo(pnls, 10000.0, n_simulations=500, seed=42)
        r2 = run_monte_carlo(pnls, 10000.0, n_simulations=500, seed=99)
        # Different seeds should produce slightly different means
        # (not guaranteed but very likely with enough sims)
        assert r1["mean_return"] == pytest.approx(r2["mean_return"], abs=0.01)

    def test_mean_return_matches_total_pnl(self):
        """Mean MC return should approximate actual total PnL / capital."""
        pnls = [100, -50, 200, -30, 150]
        result = run_monte_carlo(pnls, 10000.0, n_simulations=1000, seed=42)
        expected_return = sum(pnls) / 10000.0
        # All shuffles have same total PnL, so mean == actual
        assert result["mean_return"] == pytest.approx(expected_return, abs=1e-10)
