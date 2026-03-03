"""Tests for walk-forward validation utilities."""
from __future__ import annotations

import pytest

from scripts.walk_forward import generate_folds


class TestGenerateFolds:
    def test_basic_folds(self):
        """First two folds have correct boundaries."""
        folds = generate_folds(total_bars=10000, warmup_bars=1000, test_bars=500)
        assert len(folds) > 0
        assert folds[0] == (0, 1000, 1500)
        assert folds[1] == (500, 1500, 2000)

    def test_non_overlapping_test_periods(self):
        """Test periods of consecutive folds don't overlap."""
        folds = generate_folds(total_bars=10000, warmup_bars=1000, test_bars=500)
        for i in range(1, len(folds)):
            assert folds[i][1] == folds[i - 1][2]

    def test_warmup_size(self):
        """Each fold has correct warmup length."""
        folds = generate_folds(total_bars=10000, warmup_bars=1000, test_bars=500)
        for data_start, test_start, test_end in folds:
            assert test_start - data_start == 1000

    def test_test_size(self):
        """Each fold has correct test length."""
        folds = generate_folds(total_bars=10000, warmup_bars=1000, test_bars=500)
        for data_start, test_start, test_end in folds:
            assert test_end - test_start == 500

    def test_not_enough_data(self):
        """Returns empty list when data is shorter than one fold."""
        folds = generate_folds(total_bars=100, warmup_bars=1000, test_bars=500)
        assert folds == []

    def test_exactly_one_fold(self):
        """Exactly enough data for one fold returns single fold."""
        folds = generate_folds(total_bars=1500, warmup_bars=1000, test_bars=500)
        assert len(folds) == 1
        assert folds[0] == (0, 1000, 1500)

    def test_fold_count(self):
        """Correct number of folds for given data size."""
        # (10000 - 1000) / 500 = 18 test windows
        folds = generate_folds(total_bars=10000, warmup_bars=1000, test_bars=500)
        assert len(folds) == 18

    def test_last_fold_within_bounds(self):
        """Last fold's end doesn't exceed total_bars."""
        folds = generate_folds(total_bars=10000, warmup_bars=1000, test_bars=500)
        assert folds[-1][2] <= 10000

    def test_data_start_never_negative(self):
        """Data start index is always >= 0."""
        folds = generate_folds(total_bars=5000, warmup_bars=500, test_bars=200)
        for data_start, _, _ in folds:
            assert data_start >= 0

    def test_large_warmup(self):
        """Works with realistic lookback_bars (1640)."""
        folds = generate_folds(total_bars=17520, warmup_bars=1640, test_bars=1460)
        assert len(folds) > 0
        # Check that all folds have 1640 bars of warmup
        for data_start, test_start, _ in folds:
            assert test_start - data_start == 1640
