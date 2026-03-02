"""Tests for timeframe utility functions in config.py."""
import pytest

from src.core.config import (
    TIMEFRAME_MINUTES,
    bars_per_year,
    hours_to_bars,
    timeframe_to_minutes,
)


class TestTimeframeToMinutes:
    def test_1h(self):
        assert timeframe_to_minutes("1h") == 60

    def test_4h(self):
        assert timeframe_to_minutes("4h") == 240

    def test_1d(self):
        assert timeframe_to_minutes("1d") == 1440

    def test_1m(self):
        assert timeframe_to_minutes("1m") == 1

    def test_15m(self):
        assert timeframe_to_minutes("15m") == 15

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown timeframe"):
            timeframe_to_minutes("2w")


class TestBarsPerYear:
    def test_1h(self):
        bpy = bars_per_year("1h")
        assert abs(bpy - 8766.0) < 1.0  # 365.25 * 24

    def test_4h(self):
        bpy = bars_per_year("4h")
        assert abs(bpy - 2191.5) < 1.0  # 8766 / 4

    def test_1d(self):
        bpy = bars_per_year("1d")
        assert abs(bpy - 365.25) < 0.01

    def test_1m(self):
        bpy = bars_per_year("1m")
        assert abs(bpy - 525960.0) < 1.0  # 365.25 * 24 * 60


class TestHoursToBars:
    def test_1h_identity(self):
        """On 1h timeframe, hours == bars."""
        assert hours_to_bars(24, "1h") == 24
        assert hours_to_bars(168, "1h") == 168
        assert hours_to_bars(720, "1h") == 720

    def test_4h_conversion(self):
        """On 4h timeframe, 24h = 6 bars, 168h = 42 bars."""
        assert hours_to_bars(24, "4h") == 6
        assert hours_to_bars(168, "4h") == 42
        assert hours_to_bars(720, "4h") == 180

    def test_1d_conversion(self):
        """On 1d, 24h = 1 bar, 168h = 7 bars."""
        assert hours_to_bars(24, "1d") == 1
        assert hours_to_bars(168, "1d") == 7

    def test_15m_conversion(self):
        """On 15m, 1h = 4 bars."""
        assert hours_to_bars(1, "15m") == 4
        assert hours_to_bars(24, "15m") == 96

    def test_minimum_1_bar(self):
        """Result is always >= 1."""
        assert hours_to_bars(0, "1h") == 1
        assert hours_to_bars(0.01, "1d") == 1

    def test_float_hours(self):
        """Float input works (rounds)."""
        assert hours_to_bars(1.5, "1h") == 2
        assert hours_to_bars(0.5, "1h") == 1
