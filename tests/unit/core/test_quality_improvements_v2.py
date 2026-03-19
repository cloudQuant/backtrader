"""Tests for code quality improvements.

Covers:
- get_last_timeframe_timestamp: infinite loop fix + O(1) optimization
- AutoDict / AutoOrderedDict: dead code removal, KeyError with key info, math op fixes
- Position.__init__: dead code cleanup
- dateintern conversion functions: round-trip consistency
- mathsupport edge cases
- is_finite_real edge cases
"""

import datetime
import math
import sys
import os

import pytest

# Ensure backtrader is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from backtrader.utils.dateintern import (
    get_last_timeframe_timestamp,
    get_string_tz_time,
    timestamp2datetime,
    timestamp2datestr,
    datetime2timestamp,
    datestr2timestamp,
    str2datetime,
    datetime2str,
    num2date,
    num2dt,
    num2time,
    date2num,
    time2num,
    _num2date_cached,
    UTC,
    TZLocal,
    Localizer,
    tzparse,
)
from backtrader.utils.autodict import (
    AutoDict,
    AutoOrderedDict,
    AutoDictList,
    DotDict,
    Tree,
)
from backtrader.position import Position
from backtrader.mathsupport import average, variance, standarddev, is_finite_real


# ===========================================================================
# get_last_timeframe_timestamp tests
# ===========================================================================

class TestGetLastTimeframeTimestamp:
    """Tests for get_last_timeframe_timestamp after infinite-loop fix."""

    def test_exact_multiple(self):
        """Timestamp already aligned to timeframe."""
        assert get_last_timeframe_timestamp(120, 60) == 120

    def test_not_aligned(self):
        """Timestamp not aligned - should round down."""
        assert get_last_timeframe_timestamp(125, 60) == 120

    def test_one_second_before(self):
        """One second before next alignment."""
        assert get_last_timeframe_timestamp(179, 60) == 120

    def test_time_diff_one(self):
        """time_diff=1 should always return the timestamp itself."""
        assert get_last_timeframe_timestamp(12345, 1) == 12345

    def test_large_timestamp(self):
        """Large realistic timestamp (epoch seconds)."""
        ts = 1700000000  # ~2023-11-14
        result = get_last_timeframe_timestamp(ts, 3600)  # 1-hour
        assert result % 3600 == 0
        assert result <= ts
        assert ts - result < 3600

    def test_zero_time_diff_raises(self):
        """time_diff=0 must raise ValueError (was infinite loop before fix)."""
        with pytest.raises(ValueError, match="time_diff must be positive"):
            get_last_timeframe_timestamp(100, 0)

    def test_negative_time_diff_raises(self):
        """Negative time_diff must raise ValueError."""
        with pytest.raises(ValueError, match="time_diff must be positive"):
            get_last_timeframe_timestamp(100, -5)

    def test_timestamp_zero(self):
        """Timestamp 0 should return 0 for any positive time_diff."""
        assert get_last_timeframe_timestamp(0, 60) == 0

    def test_five_minute_bars(self):
        """5-minute bar alignment."""
        assert get_last_timeframe_timestamp(307, 300) == 300
        assert get_last_timeframe_timestamp(599, 300) == 300
        assert get_last_timeframe_timestamp(600, 300) == 600


# ===========================================================================
# AutoDict tests
# ===========================================================================

class TestAutoDict:
    """Tests for AutoDict quality improvements."""

    def test_auto_creation(self):
        """Missing keys auto-create nested AutoDicts."""
        d = AutoDict()
        d["a"]["b"] = 1
        assert d["a"]["b"] == 1

    def test_close_prevents_creation(self):
        """After _close(), missing keys raise KeyError with key info."""
        d = AutoDict()
        d["existing"] = 42
        d._close()
        with pytest.raises(KeyError) as exc_info:
            _ = d["nonexistent"]
        # Verify key info is present in the exception
        assert "nonexistent" in str(exc_info.value)

    def test_open_after_close(self):
        """_open() re-enables auto-creation."""
        d = AutoDict()
        d._close()
        d._open()
        val = d["new_key"]
        assert isinstance(val, AutoDict)

    def test_close_recursive(self):
        """_close() propagates to nested AutoDicts."""
        d = AutoDict()
        d["nested"]["deep"] = 1
        d._close()
        with pytest.raises(KeyError):
            _ = d["nested"]["new_key"]

    def test_getattr(self):
        """Attribute access works for dict keys."""
        d = AutoDict()
        d["key"] = "value"
        assert d.key == "value"

    def test_setattr(self):
        """Attribute assignment stores in dict."""
        d = AutoDict()
        d.key = "value"
        assert d["key"] == "value"


# ===========================================================================
# AutoOrderedDict tests
# ===========================================================================

class TestAutoOrderedDict:
    """Tests for AutoOrderedDict quality improvements."""

    def test_auto_creation(self):
        """Missing keys auto-create nested AutoOrderedDicts."""
        d = AutoOrderedDict()
        d["a"]["b"] = 1
        assert d["a"]["b"] == 1
        assert isinstance(d["a"], AutoOrderedDict)

    def test_close_keyerror_has_key_info(self):
        """After _close(), KeyError includes the missing key."""
        d = AutoOrderedDict()
        d._close()
        with pytest.raises(KeyError) as exc_info:
            _ = d["missing_key"]
        assert "missing_key" in str(exc_info.value)

    def test_ordered_insertion(self):
        """Keys maintain insertion order."""
        d = AutoOrderedDict()
        d["c"] = 3
        d["a"] = 1
        d["b"] = 2
        assert list(d.keys()) == ["c", "a", "b"]

    def test_iadd_numeric_coercion(self):
        """__iadd__ with number coerces to number type."""
        d = AutoOrderedDict()
        result = d.__iadd__(5)
        assert result == 5

    def test_isub_numeric_coercion(self):
        """__isub__ with number coerces to number type."""
        d = AutoOrderedDict()
        result = d.__isub__(3)
        assert result == -3

    def test_imul_numeric_coercion(self):
        """__imul__ with number coerces to number type."""
        d = AutoOrderedDict()
        result = d.__imul__(7)
        assert result == 0  # int() * 7 = 0

    def test_itruediv_numeric_coercion(self):
        """__itruediv__ with number coerces to number type."""
        d = AutoOrderedDict()
        result = d.__itruediv__(2.0)
        assert result == 0.0  # float() / 2.0 = 0.0

    def test_lvalues(self):
        """lvalues() returns list of values."""
        d = AutoOrderedDict()
        d["x"] = 10
        d["y"] = 20
        vals = d.lvalues()
        assert vals == [10, 20]

    def test_getattr_private_raises(self):
        """Accessing _private attributes raises AttributeError."""
        d = AutoOrderedDict()
        with pytest.raises(AttributeError):
            _ = d._nonexistent

    def test_setattr_private_uses_dict(self):
        """Setting _private attributes uses __dict__."""
        d = AutoOrderedDict()
        d._myattr = "hidden"
        assert d.__dict__["_myattr"] == "hidden"
        assert "_myattr" not in d  # not in the ordered dict


# ===========================================================================
# AutoDictList tests
# ===========================================================================

class TestAutoDictList:
    """Tests for AutoDictList."""

    def test_missing_key_creates_list(self):
        """Missing key creates empty list."""
        d = AutoDictList()
        d["key"].append(1)
        assert d["key"] == [1]

    def test_existing_key_preserved(self):
        """Existing keys not overwritten."""
        d = AutoDictList()
        d["key"] = [1, 2, 3]
        assert d["key"] == [1, 2, 3]


# ===========================================================================
# DotDict tests
# ===========================================================================

class TestDotDict:
    """Tests for DotDict."""

    def test_dot_access(self):
        """Attribute-style access works."""
        d = DotDict({"a": 1, "b": 2})
        assert d.a == 1
        assert d.b == 2

    def test_dunder_raises(self):
        """Dunder attributes raise via super().__getattr__."""
        d = DotDict()
        with pytest.raises((AttributeError, KeyError)):
            _ = d.__nonexistent__

    def test_missing_key_raises(self):
        """Missing non-dunder key raises KeyError."""
        d = DotDict()
        with pytest.raises(KeyError):
            _ = d.missing


# ===========================================================================
# Tree tests
# ===========================================================================

class TestTree:
    """Tests for Tree (recursive defaultdict)."""

    def test_deep_nesting(self):
        """Deeply nested access creates structure."""
        t = Tree()
        t["a"]["b"]["c"]["d"] = "deep"
        assert t["a"]["b"]["c"]["d"] == "deep"


# ===========================================================================
# Position tests
# ===========================================================================

class TestPositionQuality:
    """Tests for Position quality improvements."""

    def test_init_zero_position(self):
        """Default position has consistent zero state."""
        pos = Position()
        assert pos.size == 0
        assert pos.price == 0.0
        assert pos.upopened == 0
        assert pos.upclosed == 0

    def test_init_with_size(self):
        """Position initialized with size has correct state."""
        pos = Position(size=100, price=50.0)
        assert pos.size == 100
        assert pos.price == 50.0
        # After set(100, 50): self.size was 100 going in, size param = 100
        # size > self.size is False, so upopened = min(0, 100) = 0
        assert pos.upopened == 0
        assert pos.upclosed == 0

    def test_update_open_long(self):
        """Opening a long position from zero."""
        pos = Position()
        size, price, opened, closed = pos.update(100, 50.0)
        assert size == 100
        assert price == 50.0
        assert opened == 100
        assert closed == 0

    def test_update_close_long(self):
        """Closing a long position."""
        pos = Position()
        pos.update(100, 50.0)
        size, price, opened, closed = pos.update(-100, 55.0)
        assert size == 0
        assert price == 0.0
        assert opened == 0
        assert closed == -100

    def test_update_reverse_long_to_short(self):
        """Reversing from long to short."""
        pos = Position()
        pos.update(100, 50.0)
        size, price, opened, closed = pos.update(-150, 55.0)
        assert size == -50
        assert price == 55.0
        assert opened == -50
        assert closed == -100

    def test_update_increase_short(self):
        """Increasing a short position."""
        pos = Position()
        pos.update(-100, 50.0)
        size, price, opened, closed = pos.update(-50, 48.0)
        assert size == -150
        assert opened == -50
        assert closed == 0

    def test_update_reduce_short(self):
        """Partially reducing a short position."""
        pos = Position()
        pos.update(-100, 50.0)
        size, price, opened, closed = pos.update(30, 45.0)
        assert size == -70
        assert opened == 0
        assert closed == 30

    def test_clone(self):
        """Clone creates independent copy."""
        pos = Position(size=100, price=50.0)
        cloned = pos.clone()
        assert cloned.size == pos.size
        assert cloned.price == pos.price
        cloned.update(50, 55.0)
        assert pos.size == 100  # original unchanged

    def test_len_and_bool(self):
        """__len__ returns abs(size), __bool__ checks non-zero."""
        pos = Position(size=-50, price=100.0)
        assert len(pos) == 50
        assert bool(pos) is True

        pos_zero = Position()
        assert len(pos_zero) == 0
        assert bool(pos_zero) is False

    def test_str_representation(self):
        """__str__ produces readable output."""
        pos = Position(size=100, price=50.0)
        s = str(pos)
        assert "Size: 100" in s
        assert "Price: 50.0" in s

    def test_pseudoupdate(self):
        """pseudoupdate doesn't modify original."""
        pos = Position(size=100, price=50.0)
        result = pos.pseudoupdate(50, 60.0)
        assert pos.size == 100  # unchanged
        assert result is not None

    def test_fix(self):
        """fix() sets size and price directly."""
        pos = Position(size=100, price=50.0)
        same = pos.fix(100, 55.0)
        assert same is True
        assert pos.price == 55.0

        different = pos.fix(200, 60.0)
        assert different is False
        assert pos.size == 200


# ===========================================================================
# mathsupport tests
# ===========================================================================

class TestMathSupport:
    """Tests for mathsupport functions edge cases."""

    def test_average_empty(self):
        """Average of empty list returns 0."""
        assert average([]) == 0.0

    def test_average_single(self):
        """Average of single element."""
        assert average([5.0]) == 5.0

    def test_average_bessel_single(self):
        """Average with Bessel correction on single element (denominator=0)."""
        assert average([5.0], bessel=True) == 0.0

    def test_average_normal(self):
        """Normal average calculation."""
        assert average([1.0, 2.0, 3.0]) == 2.0

    def test_variance_empty(self):
        """Variance of empty list returns empty list."""
        assert variance([]) == []

    def test_variance_single(self):
        """Variance of single element is 0."""
        assert variance([5.0]) == [0.0]

    def test_variance_normal(self):
        """Normal variance calculation."""
        v = variance([1.0, 2.0, 3.0])
        assert len(v) == 3
        assert v[0] == pytest.approx(1.0)  # (1-2)^2
        assert v[1] == pytest.approx(0.0)  # (2-2)^2
        assert v[2] == pytest.approx(1.0)  # (3-2)^2

    def test_standarddev_empty(self):
        """Stddev of empty list returns 0."""
        assert standarddev([]) == 0.0

    def test_standarddev_normal(self):
        """Normal stddev calculation."""
        result = standarddev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        assert result == pytest.approx(2.0, abs=0.01)

    def test_is_finite_real_normal(self):
        """Finite real numbers return True."""
        assert is_finite_real(1.0) is True
        assert is_finite_real(0) is True
        assert is_finite_real(-3.14) is True

    def test_is_finite_real_nan(self):
        """NaN returns False."""
        assert is_finite_real(float("nan")) is False

    def test_is_finite_real_inf(self):
        """Infinity returns False."""
        assert is_finite_real(float("inf")) is False
        assert is_finite_real(float("-inf")) is False

    def test_is_finite_real_complex(self):
        """Complex numbers return False."""
        assert is_finite_real(1 + 2j) is False

    def test_is_finite_real_none(self):
        """None returns False (TypeError caught)."""
        assert is_finite_real(None) is False

    def test_is_finite_real_string(self):
        """String returns False (TypeError caught)."""
        assert is_finite_real("hello") is False


# ===========================================================================
# dateintern conversion round-trip tests
# ===========================================================================

class TestDateInternConversions:
    """Tests for dateintern conversion function consistency."""

    def test_num2date_date2num_roundtrip(self):
        """num2date and date2num are inverse operations."""
        dt_orig = datetime.datetime(2023, 6, 15, 14, 30, 0)
        num = date2num(dt_orig)
        dt_back = num2date(num)
        assert dt_back.year == dt_orig.year
        assert dt_back.month == dt_orig.month
        assert dt_back.day == dt_orig.day
        assert dt_back.hour == dt_orig.hour
        assert dt_back.minute == dt_orig.minute

    def test_num2date_nan_returns_epoch(self):
        """NaN input returns epoch datetime."""
        result = num2date(float("nan"))
        assert result.year == 1970

    def test_num2date_zero_returns_epoch(self):
        """Zero input returns epoch datetime."""
        result = num2date(0)
        assert result.year == 1970

    def test_num2date_negative_returns_epoch(self):
        """Negative input returns epoch datetime."""
        result = num2date(-1.0)
        assert result.year == 1970

    def test_num2dt_returns_date(self):
        """num2dt returns a date object."""
        num = date2num(datetime.datetime(2023, 1, 1))
        result = num2dt(num)
        assert isinstance(result, datetime.date)
        assert result.year == 2023

    def test_num2time_returns_time(self):
        """num2time returns a time object."""
        dt = datetime.datetime(2023, 1, 1, 15, 30, 0)
        num = date2num(dt)
        result = num2time(num)
        assert isinstance(result, datetime.time)
        assert result.hour == 15
        assert result.minute == 30

    def test_time2num_consistency(self):
        """time2num extracts correct time fraction."""
        t = datetime.time(12, 0, 0)  # noon
        num = time2num(t)
        assert num == pytest.approx(0.5, abs=1e-6)

    def test_str2datetime(self):
        """String to datetime conversion."""
        dt = str2datetime("2023-06-01 09:30:00.0")
        assert dt.year == 2023
        assert dt.month == 6
        assert dt.day == 1
        assert dt.hour == 9
        assert dt.minute == 30

    def test_datetime2str(self):
        """Datetime to string conversion."""
        dt = datetime.datetime(2023, 6, 1, 9, 30, 0, 0)
        s = datetime2str(dt)
        assert "2023-06-01" in s
        assert "09:30:00" in s

    def test_timestamp2datetime_type(self):
        """timestamp2datetime returns datetime object."""
        ts = 1685577600.0  # 2023-06-01 approx
        result = timestamp2datetime(ts)
        assert isinstance(result, datetime.datetime)

    def test_datestr2timestamp_roundtrip(self):
        """datestr -> timestamp -> datestr roundtrip."""
        s = "2023-06-01 09:30:00.000000"
        ts = datestr2timestamp(s)
        s2 = timestamp2datestr(ts)
        assert s == s2

    def test_num2date_with_timezone(self):
        """num2date with timezone returns correct result."""
        dt_orig = datetime.datetime(2023, 6, 15, 14, 30, 0)
        num = date2num(dt_orig)
        result = num2date(num, tz=UTC)
        assert result.year == 2023
        assert result.month == 6

    def test_num2date_with_tz_not_naive(self):
        """num2date with tz and naive=False includes tzinfo."""
        dt_orig = datetime.datetime(2023, 6, 15, 14, 30, 0)
        num = date2num(dt_orig)
        result = num2date(num, tz=UTC, naive=False)
        assert result.tzinfo is not None


# ===========================================================================
# Timezone utility tests
# ===========================================================================

class TestTimezoneUtils:
    """Tests for timezone utility functions."""

    def test_utc_offset_zero(self):
        """UTC offset is zero."""
        assert UTC.utcoffset(None) == datetime.timedelta(0)

    def test_utc_dst_zero(self):
        """UTC DST is zero."""
        assert UTC.dst(None) == datetime.timedelta(0)

    def test_utc_tzname(self):
        """UTC timezone name."""
        assert UTC.tzname(None) == "UTC"

    def test_utc_localize(self):
        """UTC localize adds tzinfo."""
        dt = datetime.datetime(2023, 1, 1)
        localized = UTC.localize(dt)
        assert localized.tzinfo == UTC

    def test_tzlocal_exists(self):
        """TZLocal is a valid timezone."""
        assert TZLocal is not None
        dt = datetime.datetime(2023, 6, 15, 12, 0)
        offset = TZLocal.utcoffset(dt)
        assert offset is not None

    def test_localizer_adds_localize(self):
        """Localizer adds localize method to tz without one."""
        class SimpleTZ(datetime.tzinfo):
            def utcoffset(self, dt):
                return datetime.timedelta(hours=5)
            def dst(self, dt):
                return datetime.timedelta(0)
            def tzname(self, dt):
                return "TEST"

        tz = SimpleTZ()
        assert not hasattr(tz, "localize")
        result = Localizer(tz)
        assert hasattr(result, "localize")
        dt = datetime.datetime(2023, 1, 1)
        localized = result.localize(dt)
        assert localized.tzinfo == tz

    def test_localizer_none(self):
        """Localizer(None) returns None."""
        assert Localizer(None) is None

    def test_tzparse_none(self):
        """tzparse(None) returns None."""
        assert tzparse(None) is None

    def test_tzparse_known_timezone(self):
        """tzparse with known timezone string."""
        tz = tzparse("US/Eastern")
        assert tz is not None

    def test_tzparse_cst_alias(self):
        """tzparse handles CST alias."""
        tz = tzparse("CST")
        assert tz is not None

    def test_tzparse_unknown(self):
        """tzparse with unknown timezone returns None (was crashing before fix)."""
        result = tzparse("Unknown/Timezone")
        assert result is None

    def test_get_string_tz_time(self):
        """get_string_tz_time returns formatted string."""
        result = get_string_tz_time()
        assert isinstance(result, str)
        assert len(result) > 0


# ===========================================================================
# Writer tests
# ===========================================================================

class TestWriterStringIO:
    """Tests for WriterStringIO quality."""

    def test_writer_stringio_basic(self):
        """WriterStringIO captures output."""
        from backtrader.writer import WriterStringIO
        w = WriterStringIO()
        w.start()
        w.writeline("hello")
        w.stop()
        assert "hello" in w.getvalue()

    def test_writer_stringio_multiple_lines(self):
        """WriterStringIO captures multiple lines."""
        from backtrader.writer import WriterStringIO
        w = WriterStringIO()
        w.start()
        w.writeline("line1")
        w.writeline("line2")
        w.stop()
        content = w.getvalue()
        assert "line1" in content
        assert "line2" in content

    def test_writer_separator(self):
        """WriterFile writes separator lines."""
        from backtrader.writer import WriterStringIO
        w = WriterStringIO()
        w.start()
        w.writelineseparator(level=0)
        w.stop()
        content = w.getvalue()
        assert "=" in content

    def test_writer_writelines(self):
        """WriterFile.writelines writes multiple lines."""
        from backtrader.writer import WriterStringIO
        w = WriterStringIO()
        w.start()
        w.writelines(["a", "b", "c"])
        w.stop()
        content = w.getvalue()
        assert "a" in content
        assert "c" in content
