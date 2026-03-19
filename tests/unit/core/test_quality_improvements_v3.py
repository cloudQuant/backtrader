"""Tests for code quality improvements (v3).

Tests cover:
1. DotDict.__getattr__ fix - raises clean AttributeError for dunder attributes
2. Position.set() fix - upopened tracks new size when opening from zero
3. Position.__repr__ and __eq__ additions
4. WriterFile context manager support and safer stop()
5. mathsupport edge cases
6. AutoDict/AutoOrderedDict robustness
7. List.__contains__ fix - identity check instead of hash comparison
8. Trade.__repr__ addition
9. OrderExecutionBit.__repr__ addition
"""

import io
import math
import os
import tempfile

import pytest

from backtrader.functions import List
from backtrader.mathsupport import average, is_finite_real, standarddev, variance
from backtrader.order import OrderExecutionBit
from backtrader.position import Position
from backtrader.trade import Trade
from backtrader.utils.autodict import AutoDict, AutoOrderedDict, DotDict
from backtrader.writer import WriterFile, WriterStringIO


# ───────────────────────────────────────────────────────────────────────────
# 1. DotDict.__getattr__ fix
# ───────────────────────────────────────────────────────────────────────────


class TestDotDictGetattr:
    """Tests for DotDict.__getattr__ fix."""

    def test_normal_attribute_access(self):
        """DotDict should allow attribute-style access to dict keys."""
        d = DotDict({"foo": 1, "bar": "hello"})
        assert d.foo == 1
        assert d.bar == "hello"

    def test_dunder_attribute_raises_attribute_error(self):
        """Accessing dunder attributes should raise AttributeError, not TypeError."""
        d = DotDict({"key": "value"})
        with pytest.raises(AttributeError, match="__nonexistent__"):
            _ = d.__nonexistent__

    def test_dunder_len_still_works(self):
        """Built-in dunder methods like __len__ should still work."""
        d = DotDict({"a": 1, "b": 2})
        assert len(d) == 2

    def test_missing_key_raises_key_error(self):
        """Accessing a non-existent non-dunder key raises KeyError."""
        d = DotDict({"a": 1})
        with pytest.raises(KeyError):
            _ = d.nonexistent

    def test_setattr_and_getattr(self):
        """DotDict should support setting via dict and reading via attr."""
        d = DotDict()
        d["mykey"] = 42
        assert d.mykey == 42

    def test_unknown_dunder_raises_clean_error(self):
        """Unknown dunder attributes should raise AttributeError with the key name."""
        d = DotDict({"x": 1})
        with pytest.raises(AttributeError, match="__fake_dunder__"):
            _ = d.__fake_dunder__
        with pytest.raises(AttributeError, match="__xyz__"):
            _ = d.__xyz__


# ───────────────────────────────────────────────────────────────────────────
# 2. Position.set() fix - upopened when opening from zero
# ───────────────────────────────────────────────────────────────────────────


class TestPositionSetFix:
    """Tests for Position.set() upopened fix."""

    def test_set_from_zero_to_long(self):
        """When set() transitions from 0 to a long position, upopened should equal new size."""
        pos = Position(size=0, price=0.0)
        assert pos.size == 0
        pos.set(100, 50.0)
        assert pos.size == 100
        assert pos.price == 50.0
        assert pos.upopened == 100
        assert pos.upclosed == 0

    def test_set_from_zero_to_short(self):
        """When set() transitions from 0 to a short position, upopened should be negative."""
        pos = Position(size=0, price=0.0)
        pos.set(-50, 30.0)
        assert pos.size == -50
        assert pos.price == 30.0
        assert pos.upopened == -50
        assert pos.upclosed == 0

    def test_set_from_zero_to_zero(self):
        """When set() is called with 0 on a 0 position, upopened should be 0."""
        pos = Position(size=0, price=0.0)
        pos.set(0, 0.0)
        assert pos.upopened == 0
        assert pos.upclosed == 0

    def test_set_increase_long(self):
        """set() increasing a long position should track the increase."""
        pos = Position(size=10, price=50.0)
        pos.set(15, 55.0)
        assert pos.upopened == 5  # 15 - 10
        assert pos.upclosed == 0

    def test_set_decrease_long(self):
        """set() decreasing a long position should track the close."""
        pos = Position(size=10, price=50.0)
        pos.set(5, 45.0)
        assert pos.upopened == 0
        assert pos.upclosed == 5  # closed 5 of 10

    def test_set_reverse_long_to_short(self):
        """set() reversing a long position should track both close and open."""
        pos = Position(size=10, price=50.0)
        pos.set(-5, 60.0)
        assert pos.upopened == -5  # opened short
        assert pos.upclosed == 10  # closed all 10 long

    def test_set_increase_short(self):
        """set() increasing a short position."""
        pos = Position(size=-10, price=50.0)
        pos.set(-15, 45.0)
        assert pos.upopened == -5  # -15 - (-10) = -5
        assert pos.upclosed == 0

    def test_set_decrease_short(self):
        """set() decreasing a short position should track the close."""
        pos = Position(size=-10, price=50.0)
        pos.set(-5, 55.0)
        assert pos.upopened == 0
        assert pos.upclosed == -5  # closed 5 of -10

    def test_set_returns_tuple(self):
        """set() should return (size, price, upopened, upclosed)."""
        pos = Position(size=0, price=0.0)
        result = pos.set(100, 50.0)
        assert result == (100, 50.0, 100, 0)


# ───────────────────────────────────────────────────────────────────────────
# 3. Position.__repr__ and __eq__
# ───────────────────────────────────────────────────────────────────────────


class TestPositionReprEq:
    """Tests for Position.__repr__ and __eq__."""

    def test_repr(self):
        """Position should have a readable repr."""
        pos = Position(size=10, price=50.0)
        r = repr(pos)
        assert "Position" in r
        assert "size=10" in r
        assert "price=50.0" in r

    def test_repr_empty(self):
        """Empty position repr."""
        pos = Position()
        r = repr(pos)
        assert "size=0" in r
        assert "price=0.0" in r

    def test_eq_same(self):
        """Two positions with same size and price should be equal."""
        p1 = Position(size=10, price=50.0)
        p2 = Position(size=10, price=50.0)
        assert p1 == p2

    def test_eq_different_size(self):
        """Positions with different sizes should not be equal."""
        p1 = Position(size=10, price=50.0)
        p2 = Position(size=20, price=50.0)
        assert p1 != p2

    def test_eq_different_price(self):
        """Positions with different prices should not be equal."""
        p1 = Position(size=10, price=50.0)
        p2 = Position(size=10, price=60.0)
        assert p1 != p2

    def test_eq_not_implemented_for_other_types(self):
        """Comparing Position to non-Position returns NotImplemented."""
        pos = Position(size=10, price=50.0)
        assert pos.__eq__("not a position") is NotImplemented
        assert pos.__eq__(10) is NotImplemented


# ───────────────────────────────────────────────────────────────────────────
# 4. WriterFile context manager and safer stop
# ───────────────────────────────────────────────────────────────────────────


class TestWriterContextManager:
    """Tests for WriterFile context manager support."""

    def test_context_manager_with_file(self, tmp_path):
        """WriterFile should support context manager protocol with file output."""
        outfile = str(tmp_path / "test_output.txt")
        writer = WriterFile(out=outfile)
        with writer:
            writer.writeline("test line 1")
            writer.writeline("test line 2")

        # File should be written and closed
        with open(outfile, "r") as f:
            content = f.read()
        assert "test line 1" in content
        assert "test line 2" in content

    def test_context_manager_with_stringio(self):
        """WriterFile should support context manager with StringIO."""
        sio = io.StringIO()
        writer = WriterFile(out=sio, close_out=False)
        with writer:
            writer.writeline("hello")

        sio.seek(0)
        assert "hello" in sio.read()

    def test_stop_handles_already_closed_file(self, tmp_path):
        """stop() should not raise if file is already closed."""
        outfile = str(tmp_path / "test_close.txt")
        writer = WriterFile(out=outfile)
        writer.start()
        writer.writeline("data")
        writer.out.close()  # manually close
        writer.stop()  # should not raise

    def test_exit_returns_false(self):
        """__exit__ should return False (don't suppress exceptions)."""
        writer = WriterFile()
        writer._start_output()
        result = writer.__exit__(None, None, None)
        assert result is False


# ───────────────────────────────────────────────────────────────────────────
# 5. mathsupport edge cases
# ───────────────────────────────────────────────────────────────────────────


class TestMathsupportEdgeCases:
    """Tests for mathsupport edge case handling."""

    def test_average_empty_list(self):
        """average([]) should return 0.0, not raise."""
        assert average([]) == 0.0

    def test_average_single_element(self):
        """average of single element should return that element."""
        assert average([5.0]) == 5.0

    def test_average_with_bessel_single_element(self):
        """average([x], bessel=True) should return 0.0 (denominator is 0)."""
        assert average([5.0], bessel=True) == 0.0

    def test_average_normal(self):
        """Normal average calculation."""
        assert average([1.0, 2.0, 3.0]) == 2.0

    def test_variance_empty(self):
        """variance([]) should return empty list."""
        assert variance([]) == []

    def test_variance_single(self):
        """variance of single element should be [0.0]."""
        assert variance([5.0]) == [0.0]

    def test_standarddev_empty(self):
        """standarddev([]) should return 0.0, not raise."""
        assert standarddev([]) == 0.0

    def test_standarddev_single(self):
        """standarddev of single element should be 0.0."""
        assert standarddev([5.0]) == 0.0

    def test_standarddev_single_bessel(self):
        """standarddev of single element with bessel should be 0.0."""
        assert standarddev([5.0], bessel=True) == 0.0

    def test_standarddev_known_values(self):
        """standarddev with known values."""
        data = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        result = standarddev(data)
        assert abs(result - 2.0) < 0.001

    def test_is_finite_real_valid(self):
        """is_finite_real should return True for finite real numbers."""
        assert is_finite_real(1.0) is True
        assert is_finite_real(0) is True
        assert is_finite_real(-42.5) is True

    def test_is_finite_real_invalid(self):
        """is_finite_real should return False for non-finite or non-real values."""
        assert is_finite_real(float("nan")) is False
        assert is_finite_real(float("inf")) is False
        assert is_finite_real(float("-inf")) is False
        assert is_finite_real(complex(1, 2)) is False
        assert is_finite_real(None) is False
        assert is_finite_real("string") is False


# ───────────────────────────────────────────────────────────────────────────
# 6. AutoDict/AutoOrderedDict robustness
# ───────────────────────────────────────────────────────────────────────────


class TestAutoDictRobustness:
    """Tests for AutoDict and AutoOrderedDict robustness."""

    def test_autodict_close_prevents_auto_creation(self):
        """Closing an AutoDict should prevent auto-creation of keys."""
        ad = AutoDict()
        ad["existing"] = 1
        ad._close()
        with pytest.raises(KeyError):
            _ = ad["nonexistent"]

    def test_autodict_open_after_close(self):
        """Opening a closed AutoDict should allow auto-creation again."""
        ad = AutoDict()
        ad._close()
        ad._open()
        nested = ad["newkey"]
        assert isinstance(nested, AutoDict)

    def test_autodict_open_reopens_nested_children(self):
        ad = AutoDict()
        ad["parent"]["child"] = 1
        ad._close()
        ad._open()
        ad["parent"]["newchild"] = 2
        assert ad["parent"]["newchild"] == 2

    def test_autoordered_close_prevents_auto_creation(self):
        """Closing an AutoOrderedDict should prevent auto-creation."""
        aod = AutoOrderedDict()
        aod["existing"] = 1
        aod._close()
        with pytest.raises(KeyError):
            _ = aod["nonexistent"]

    def test_autoordered_open_after_close(self):
        """Opening a closed AutoOrderedDict should allow auto-creation."""
        aod = AutoOrderedDict()
        aod._close()
        aod._open()
        nested = aod["newkey"]
        assert isinstance(nested, AutoOrderedDict)

    def test_autoordered_open_reopens_nested_children(self):
        aod = AutoOrderedDict()
        aod["parent"]["child"] = 1
        aod._close()
        aod._open()
        aod["parent"]["newchild"] = 2
        assert aod["parent"]["newchild"] == 2

    def test_autodict_nested_creation(self):
        """AutoDict should support multi-level nested auto-creation."""
        ad = AutoDict()
        ad["a"]["b"]["c"] = "deep"
        assert ad["a"]["b"]["c"] == "deep"

    def test_autoordered_iadd(self):
        """AutoOrderedDict __iadd__ should convert to value type."""
        aod = AutoOrderedDict()
        aod["count"] += 5
        assert aod["count"] == 5

    def test_autoordered_isub(self):
        """AutoOrderedDict __isub__ should work."""
        aod = AutoOrderedDict()
        aod["val"] -= 3
        assert aod["val"] == -3


# ───────────────────────────────────────────────────────────────────────────
# 7. WriterStringIO
# ───────────────────────────────────────────────────────────────────────────


class TestWriterStringIO:
    """Tests for WriterStringIO."""

    def test_stringio_getvalue(self):
        """WriterStringIO should accumulate content."""
        writer = WriterStringIO()
        writer.start()
        writer.writeline("line1")
        writer.writeline("line2")
        content = writer.getvalue()
        assert "line1" in content
        assert "line2" in content

    def test_stringio_stop_seeks_beginning(self):
        """stop() should seek to beginning for reading."""
        writer = WriterStringIO()
        writer.start()
        writer.writeline("content")
        writer.stop()
        # After stop, should be able to read from beginning
        content = writer.out.read()
        assert "content" in content


# ───────────────────────────────────────────────────────────────────────────
# 8. Position update edge cases
# ───────────────────────────────────────────────────────────────────────────


class TestPositionUpdateEdgeCases:
    """Additional edge case tests for Position.update()."""

    def test_update_from_zero(self):
        """update() from zero should correctly track opened amount."""
        pos = Position(size=0, price=0.0)
        nsize, nprice, opened, closed = pos.update(size=10, price=50.0)
        assert nsize == 10
        assert nprice == 50.0
        assert opened == 10
        assert closed == 0

    def test_update_to_zero(self):
        """update() to zero should correctly track closed amount."""
        pos = Position(size=10, price=50.0)
        nsize, nprice, opened, closed = pos.update(size=-10, price=60.0)
        assert nsize == 0
        assert nprice == 0.0
        assert opened == 0
        assert closed == -10

    def test_clone(self):
        """Position.clone() should create independent copy."""
        pos = Position(size=10, price=50.0)
        clone = pos.clone()
        assert clone.size == pos.size
        assert clone.price == pos.price
        # Modify clone shouldn't affect original
        clone.update(size=5, price=60.0)
        assert pos.size == 10


# ───────────────────────────────────────────────────────────────────────────
# 9. List.__contains__ fix - identity check
# ───────────────────────────────────────────────────────────────────────────


class TestListIdentityContains:
    """Tests for List.__contains__ using identity ('is') instead of hash."""

    def test_identity_check_same_object(self):
        """List should find the same object via identity."""
        obj = object()
        lst = List([obj])
        assert obj in lst

    def test_identity_check_different_object(self):
        """List should not find a different object even with same value."""
        a = [1, 2, 3]
        b = [1, 2, 3]
        lst = List([a])
        # a and b are equal but not the same object
        assert a in lst
        assert b not in lst  # identity check, not equality

    def test_identity_check_integers_small(self):
        """Small integers are interned, so identity works."""
        x = 42
        lst = List([x])
        assert x in lst

    def test_empty_list(self):
        """Empty List should not contain anything."""
        lst = List()
        assert "anything" not in lst

    def test_multiple_items(self):
        """List with multiple items should find the right one by identity."""
        a = object()
        b = object()
        c = object()
        lst = List([a, b, c])
        assert a in lst
        assert b in lst
        assert c in lst
        assert object() not in lst


# ───────────────────────────────────────────────────────────────────────────
# 10. Trade.__repr__
# ───────────────────────────────────────────────────────────────────────────


class TestTradeRepr:
    """Tests for Trade.__repr__."""

    def test_repr_created(self):
        """Trade repr should show status and key fields."""
        trade = Trade(size=0, price=0.0)
        r = repr(trade)
        assert "Trade" in r
        assert "size=0" in r
        assert "Created" in r

    def test_repr_fields(self):
        """Trade repr should include ref, size, price, pnl, status."""
        trade = Trade(size=10, price=50.0)
        r = repr(trade)
        assert "ref=" in r
        assert "price=50.0" in r
        assert "pnl=" in r

    def test_str_still_works(self):
        """Existing __str__ should still work."""
        trade = Trade(size=5, price=100.0)
        s = str(trade)
        assert "size" in s
        assert "price" in s


# ───────────────────────────────────────────────────────────────────────────
# 11. OrderExecutionBit.__repr__
# ───────────────────────────────────────────────────────────────────────────


class TestOrderExecutionBitRepr:
    """Tests for OrderExecutionBit.__repr__."""

    def test_repr_default(self):
        """Default OrderExecutionBit repr."""
        bit = OrderExecutionBit()
        r = repr(bit)
        assert "OrderExecutionBit" in r
        assert "size=0" in r
        assert "price=0.0" in r

    def test_repr_with_values(self):
        """OrderExecutionBit repr with specific values."""
        bit = OrderExecutionBit(
            size=100, price=50.0, closed=50, opened=50, pnl=250.0
        )
        r = repr(bit)
        assert "size=100" in r
        assert "price=50.0" in r
        assert "closed=50" in r
        assert "opened=50" in r
        assert "pnl=250.0" in r

    def test_value_and_comm_computed(self):
        """OrderExecutionBit should correctly compute value and comm."""
        bit = OrderExecutionBit(
            closedvalue=100.0, openedvalue=200.0,
            closedcomm=5.0, openedcomm=10.0,
        )
        assert bit.value == 300.0
        assert bit.comm == 15.0
