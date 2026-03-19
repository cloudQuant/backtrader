"""Tests for code quality improvements v4.

Covers:
- AutoDict/AutoOrderedDict: __getattr__ raises AttributeError with key info
- Position: explicit __hash__ = None for mutable object
- Trade.__repr__: bounds-safe status name lookup
- mathsupport: empty sequence guards for variance() and standarddev()
- CommInfo subclasses: get_margin guards against None margin
"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from backtrader.comminfo import (
    ComminfoDC,
    ComminfoFuturesFixed,
    ComminfoFuturesPercent,
    ComminfoFundingRate,
)
from backtrader.mathsupport import average, standarddev, variance
from backtrader.position import Position
from backtrader.trade import Trade
from backtrader.utils.autodict import AutoDict, AutoOrderedDict


# ===========================================================================
# AutoDict.__getattr__ improvements
# ===========================================================================


class TestAutoDictGetattr:
    """Tests for AutoDict.__getattr__ raising AttributeError with key info."""

    def test_closed_autodict_getattr_raises_attribute_error(self):
        """Closed AutoDict attribute access raises AttributeError (not KeyError)."""
        d = AutoDict()
        d["existing"] = 42
        d._close()
        with pytest.raises(AttributeError, match="nonexistent"):
            _ = d.nonexistent

    def test_private_attr_raises_attribute_error_with_key(self):
        """Private attribute access raises AttributeError with key name."""
        d = AutoDict()
        with pytest.raises(AttributeError, match="_private"):
            _ = d._private

    def test_open_autodict_getattr_creates_nested(self):
        """Open AutoDict attribute access still auto-creates nested dicts."""
        d = AutoDict()
        val = d.new_key
        assert isinstance(val, AutoDict)

    def test_existing_key_getattr_works(self):
        """Attribute access for existing keys works normally."""
        d = AutoDict()
        d["mykey"] = "myvalue"
        assert d.mykey == "myvalue"


# ===========================================================================
# AutoOrderedDict.__getattr__ improvements
# ===========================================================================


class TestAutoOrderedDictGetattr:
    """Tests for AutoOrderedDict.__getattr__ raising AttributeError with key info."""

    def test_closed_aod_getattr_raises_attribute_error(self):
        """Closed AutoOrderedDict attribute access raises AttributeError."""
        d = AutoOrderedDict()
        d["existing"] = 42
        d._close()
        with pytest.raises(AttributeError, match="nonexistent"):
            _ = d.nonexistent

    def test_private_attr_raises_attribute_error_with_key(self):
        """Private attribute access raises AttributeError with key name."""
        d = AutoOrderedDict()
        with pytest.raises(AttributeError, match="_private"):
            _ = d._private

    def test_open_aod_getattr_creates_nested(self):
        """Open AutoOrderedDict attribute access still auto-creates nested."""
        d = AutoOrderedDict()
        val = d.new_key
        assert isinstance(val, AutoOrderedDict)

    def test_existing_key_getattr_works(self):
        """Attribute access for existing keys works normally."""
        d = AutoOrderedDict()
        d["mykey"] = "myvalue"
        assert d.mykey == "myvalue"

    def test_hasattr_works_on_closed_aod(self):
        """hasattr() works correctly on closed AutoOrderedDict."""
        d = AutoOrderedDict()
        d["exists"] = 1
        d._close()
        assert hasattr(d, "exists")
        assert not hasattr(d, "nonexistent")


# ===========================================================================
# Position.__hash__ = None
# ===========================================================================


class TestPositionHash:
    """Tests for Position explicit __hash__ = None."""

    def test_position_is_unhashable(self):
        """Position instances cannot be hashed (mutable object)."""
        p = Position(size=10, price=100.0)
        with pytest.raises(TypeError, match="unhashable"):
            hash(p)

    def test_position_cannot_be_in_set(self):
        """Position instances cannot be added to sets."""
        p = Position(size=10, price=100.0)
        with pytest.raises(TypeError):
            {p}

    def test_position_cannot_be_dict_key(self):
        """Position instances cannot be used as dict keys."""
        p = Position(size=10, price=100.0)
        with pytest.raises(TypeError):
            {p: "value"}

    def test_position_equality_still_works(self):
        """Position equality comparison still works correctly."""
        p1 = Position(size=10, price=100.0)
        p2 = Position(size=10, price=100.0)
        p3 = Position(size=20, price=100.0)
        assert p1 == p2
        assert p1 != p3


# ===========================================================================
# Trade.__repr__ bounds safety
# ===========================================================================


class TestTradeRepr:
    """Tests for Trade.__repr__ bounds-safe status name lookup."""

    def test_repr_normal_status(self):
        """__repr__ works for normal status values."""
        t = Trade()
        assert "Created" in repr(t)

    def test_repr_open_status(self):
        """__repr__ works for Open status."""
        t = Trade()
        t.status = Trade.Open
        assert "Open" in repr(t)

    def test_repr_closed_status(self):
        """__repr__ works for Closed status."""
        t = Trade()
        t.status = Trade.Closed
        assert "Closed" in repr(t)

    def test_repr_invalid_status_no_crash(self):
        """__repr__ does not crash with out-of-range status."""
        t = Trade()
        t.status = 999
        result = repr(t)
        assert "Unknown(999)" in result

    def test_repr_none_status_no_crash(self):
        """__repr__ does not crash with None status."""
        t = Trade()
        t.status = None
        result = repr(t)
        assert "Unknown(None)" in result


# ===========================================================================
# mathsupport empty sequence guards
# ===========================================================================


class TestMathsupportEmptyGuards:
    """Tests for mathsupport handling of empty sequences."""

    def test_variance_empty_returns_empty_list(self):
        """variance() with empty input returns empty list."""
        result = variance([])
        assert result == []

    def test_variance_normal(self):
        """variance() with normal input still works correctly."""
        result = variance([2, 4, 4, 4, 5, 5, 7, 9])
        assert len(result) == 8
        assert all(isinstance(v, float) for v in result)

    def test_standarddev_empty_returns_zero(self):
        """standarddev() with empty input returns 0.0."""
        result = standarddev([])
        assert result == 0.0

    def test_standarddev_normal(self):
        """standarddev() with normal input still works correctly."""
        result = standarddev([2, 4, 4, 4, 5, 5, 7, 9])
        assert isinstance(result, float)
        assert result > 0

    def test_standarddev_single_element(self):
        """standarddev() with single element returns 0.0."""
        result = standarddev([5.0])
        assert result == 0.0

    def test_standarddev_bessel_empty(self):
        """standarddev() with bessel=True and empty input returns 0.0."""
        result = standarddev([], bessel=True)
        assert result == 0.0

    def test_average_empty_returns_zero(self):
        """average() with empty input returns 0.0."""
        result = average([])
        assert result == 0.0

    def test_standarddev_identical_values(self):
        """standarddev() with identical values returns 0.0."""
        result = standarddev([3.0, 3.0, 3.0, 3.0])
        assert result == 0.0


# ===========================================================================
# CommInfo subclass get_margin None guard
# ===========================================================================


class TestCommInfoGetMarginNoneGuard:
    """Tests for CommInfo subclasses guarding against None margin."""

    def test_comminfo_dc_none_margin_fallback(self):
        """ComminfoDC.get_margin returns sensible value when margin is None."""
        ci = ComminfoDC()
        # Even if margin ends up None somehow, should not crash
        result = ci.get_margin(100.0)
        assert isinstance(result, (int, float))
        assert math.isfinite(result)

    def test_comminfo_futures_percent_none_margin_fallback(self):
        """ComminfoFuturesPercent.get_margin handles None margin."""
        ci = ComminfoFuturesPercent()
        result = ci.get_margin(100.0)
        assert isinstance(result, (int, float))
        assert math.isfinite(result)

    def test_comminfo_futures_fixed_none_margin_fallback(self):
        """ComminfoFuturesFixed.get_margin handles None margin."""
        ci = ComminfoFuturesFixed()
        result = ci.get_margin(100.0)
        assert isinstance(result, (int, float))
        assert math.isfinite(result)

    def test_comminfo_funding_rate_none_margin_fallback(self):
        """ComminfoFundingRate.get_margin handles None margin."""
        ci = ComminfoFundingRate()
        result = ci.get_margin(100.0)
        assert isinstance(result, (int, float))
        assert math.isfinite(result)

    def test_comminfo_dc_explicit_margin(self):
        """ComminfoDC.get_margin works correctly with explicit margin."""
        ci = ComminfoDC(margin=0.1)
        result = ci.get_margin(1000.0)
        # price * mult * margin = 1000 * 1.0 * 0.1 = 100.0
        assert result == pytest.approx(100.0)

    def test_comminfo_futures_percent_explicit_margin(self):
        """ComminfoFuturesPercent.get_margin works with explicit margin."""
        ci = ComminfoFuturesPercent(margin=0.05, mult=10.0)
        result = ci.get_margin(5000.0)
        # price * mult * margin = 5000 * 10.0 * 0.05 = 2500.0
        assert result == pytest.approx(2500.0)
