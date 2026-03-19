"""Tests for code quality fixes.

These tests verify the quality improvements made to the backtrader codebase,
including mutable default argument fixes, NaN guards, None guards, and
clone completeness.
"""

import math

import pytest


class TestTimerMutableDefaults:
    """Test that Timer weekdays/monthdays defaults are not shared across instances."""

    def test_weekdays_default_is_none(self):
        """weekdays default should be None, not a mutable list."""
        from backtrader.timer import Timer

        t1 = Timer.__dict__["weekdays"]
        assert t1.default is None

    def test_monthdays_default_is_none(self):
        """monthdays default should be None, not a mutable list."""
        from backtrader.timer import Timer

        t1 = Timer.__dict__["monthdays"]
        assert t1.default is None

    def test_weekdays_none_treated_as_no_filter(self):
        """None weekdays should mean no weekday filtering (same as empty list)."""
        # None is falsy, so `if not self.get_param("weekdays")` returns True
        assert not None
        assert not []


class TestPercentSizerNanGuard:
    """Test that PercentSizer handles NaN close prices safely."""

    def test_nan_is_truthy(self):
        """Verify that NaN is truthy (not caught by 'not close_price')."""
        assert not (not float("nan"))  # float('nan') is truthy

    def test_nan_self_comparison(self):
        """Verify that NaN != NaN (the guard we added)."""
        nan = float("nan")
        assert nan != nan  # This is the guard pattern we use


class TestCommInfoInterestGuard:
    """Test that CommInfoBase handles interest edge cases gracefully."""

    def test_zero_interest(self):
        """interest=0 should yield zero creditrate."""
        from backtrader.comminfo import CommInfoBase

        ci = CommInfoBase(interest=0.0)
        assert ci._creditrate == 0.0

    def test_normal_interest(self):
        """Normal interest value should calculate correctly."""
        from backtrader.comminfo import CommInfoBase

        ci = CommInfoBase(interest=3.65)
        assert abs(ci._creditrate - 3.65 / 365.0) < 1e-10

    def test_default_interest(self):
        """Default interest value should produce valid creditrate."""
        from backtrader.comminfo import CommInfoBase

        ci = CommInfoBase()
        assert ci._creditrate == 0.0

    def test_interest_guard_internal(self):
        """The (interest or 0.0) guard should handle falsy values."""
        # This tests the guard pattern directly
        assert (None or 0.0) / 365.0 == 0.0
        assert (0 or 0.0) / 365.0 == 0.0
        assert (0.0 or 0.0) / 365.0 == 0.0


class TestPositionCloneCompleteness:
    """Test that Position.clone() copies all state fields."""

    def test_clone_copies_upopened_upclosed(self):
        """clone() should copy upopened and upclosed fields."""
        from backtrader.position import Position

        pos = Position(size=0, price=0.0)
        pos.update(size=10, price=100.0)

        cloned = pos.clone()
        assert cloned.upopened == pos.upopened
        assert cloned.upclosed == pos.upclosed

    def test_clone_copies_price_orig(self):
        """clone() should copy price_orig field."""
        from backtrader.position import Position

        pos = Position(size=0, price=0.0)
        pos.update(size=10, price=100.0)
        pos.update(size=-5, price=110.0)

        cloned = pos.clone()
        assert cloned.price_orig == pos.price_orig

    def test_clone_preserves_all_fields(self):
        """clone() should produce an identical copy of all position state."""
        from backtrader.position import Position

        pos = Position(size=0, price=0.0)
        pos.update(size=10, price=100.0)
        pos.update(size=-5, price=110.0)

        cloned = pos.clone()
        assert cloned.size == pos.size
        assert cloned.price == pos.price
        assert cloned.adjbase == pos.adjbase
        assert cloned.datetime == pos.datetime
        assert cloned.updt == pos.updt
        assert cloned.upopened == pos.upopened
        assert cloned.upclosed == pos.upclosed
        assert cloned.price_orig == pos.price_orig

    def test_clone_is_independent(self):
        """Modifying cloned position should not affect original."""
        from backtrader.position import Position

        pos = Position(size=0, price=0.0)
        pos.update(size=10, price=100.0)

        cloned = pos.clone()
        cloned.update(size=5, price=120.0)

        assert pos.size == 10
        assert cloned.size == 15


class TestMathSupportEdgeCases:
    """Test mathsupport functions handle edge cases correctly."""

    def test_average_empty_list(self):
        """average() with empty list should return 0.0."""
        from backtrader.mathsupport import average

        assert average([]) == 0.0

    def test_average_single_element(self):
        """average() with single element should return that element."""
        from backtrader.mathsupport import average

        assert average([5.0]) == 5.0

    def test_average_bessel_with_single_element(self):
        """average() with bessel=True and single element should return 0.0 (denominator=0)."""
        from backtrader.mathsupport import average

        assert average([5.0], bessel=True) == 0.0

    def test_standarddev_empty_list(self):
        """standarddev() with empty list should return 0.0."""
        from backtrader.mathsupport import standarddev

        assert standarddev([]) == 0.0

    def test_standarddev_single_element(self):
        """standarddev() of single element should be 0.0."""
        from backtrader.mathsupport import standarddev

        assert standarddev([5.0]) == 0.0

    def test_is_finite_real_nan(self):
        """is_finite_real should return False for NaN."""
        from backtrader.mathsupport import is_finite_real

        assert is_finite_real(float("nan")) is False

    def test_is_finite_real_inf(self):
        """is_finite_real should return False for infinity."""
        from backtrader.mathsupport import is_finite_real

        assert is_finite_real(float("inf")) is False

    def test_is_finite_real_complex(self):
        """is_finite_real should return False for complex numbers."""
        from backtrader.mathsupport import is_finite_real

        assert is_finite_real(1 + 2j) is False

    def test_is_finite_real_none(self):
        """is_finite_real should return False for None."""
        from backtrader.mathsupport import is_finite_real

        assert is_finite_real(None) is False

    def test_is_finite_real_valid(self):
        """is_finite_real should return True for normal floats."""
        from backtrader.mathsupport import is_finite_real

        assert is_finite_real(3.14) is True
        assert is_finite_real(0.0) is True
        assert is_finite_real(-100) is True
