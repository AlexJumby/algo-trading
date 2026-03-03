"""Tests for drawdown-based deleveraging in PositionSizer."""
import pytest

from src.core.config import RiskConfig
from src.core.enums import SignalAction
from src.core.models import Signal
from src.risk.position_sizer import PositionSizer


def _make_signal() -> Signal:
    return Signal(
        timestamp=0, symbol="BTC/USDT:USDT",
        action=SignalAction.LONG, strength=1.0,
    )


def _make_sizer(soft: float = 0.10, hard: float = 0.25) -> PositionSizer:
    config = RiskConfig(
        max_position_size_pct=0.10,
        max_drawdown_pct=hard,
        drawdown_soft_pct=soft,
    )
    return PositionSizer(config)


class TestDrawdownDeleveraging:
    def test_no_deleverage_below_soft(self):
        """Below soft threshold → full position."""
        sizer = _make_sizer(soft=0.10, hard=0.25)
        base = sizer.compute_size(10000, 50000, _make_signal(), drawdown_pct=0.05)
        full = sizer.compute_size(10000, 50000, _make_signal(), drawdown_pct=0.0)
        assert base == full

    def test_full_deleverage_at_hard(self):
        """At hard threshold → zero position."""
        sizer = _make_sizer(soft=0.10, hard=0.25)
        qty = sizer.compute_size(10000, 50000, _make_signal(), drawdown_pct=0.25)
        assert qty == 0.0

    def test_linear_midpoint(self):
        """Midpoint between soft and hard → 50% position."""
        sizer = _make_sizer(soft=0.10, hard=0.30)
        full = sizer.compute_size(10000, 50000, _make_signal(), drawdown_pct=0.0)
        mid = sizer.compute_size(10000, 50000, _make_signal(), drawdown_pct=0.20)
        assert abs(mid - full * 0.5) < 1e-10

    def test_soft_boundary_exact(self):
        """At exactly soft threshold → still full position."""
        sizer = _make_sizer(soft=0.10, hard=0.25)
        full = sizer.compute_size(10000, 50000, _make_signal(), drawdown_pct=0.0)
        at_soft = sizer.compute_size(10000, 50000, _make_signal(), drawdown_pct=0.10)
        assert at_soft == full

    def test_between_soft_and_hard(self):
        """Between soft and hard → reduced but non-zero."""
        sizer = _make_sizer(soft=0.10, hard=0.25)
        full = sizer.compute_size(10000, 50000, _make_signal(), drawdown_pct=0.0)
        reduced = sizer.compute_size(10000, 50000, _make_signal(), drawdown_pct=0.15)
        assert 0 < reduced < full

    def test_above_hard_is_zero(self):
        """Above hard threshold → still zero."""
        sizer = _make_sizer(soft=0.10, hard=0.25)
        qty = sizer.compute_size(10000, 50000, _make_signal(), drawdown_pct=0.30)
        assert qty == 0.0

    def test_deleverage_disabled_when_soft_zero(self):
        """soft=0 → deleveraging disabled, full position regardless."""
        sizer = _make_sizer(soft=0.0, hard=0.25)
        full = sizer.compute_size(10000, 50000, _make_signal(), drawdown_pct=0.0)
        at_dd = sizer.compute_size(10000, 50000, _make_signal(), drawdown_pct=0.20)
        assert at_dd == full

    def test_config_has_drawdown_soft_pct(self):
        """RiskConfig has the new field with correct default."""
        config = RiskConfig()
        assert hasattr(config, "drawdown_soft_pct")
        assert config.drawdown_soft_pct == 0.10
