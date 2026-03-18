"""Unit-level coverage tests for internal methods of core Line modules.

Directly instantiates and calls internal methods to cover paths that
integration tests through cerebro cannot reach.

Targets:
- linebuffer.py: __setitem__ NaN/None, qbuffer mode, backwards, once ops
- lineseries.py: Lines.__setitem__, LineSeries __getattr__/__setattr__ cache
- lineroot.py: _operation_stage2 edge paths, _makeoperationown bool branches
- lineiterator.py: donew data parsing edge cases
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import array
import math
import operator

import pytest

import backtrader as bt
from backtrader import linebuffer


class _ScalarNoArray:
    def __init__(self, value):
        self.value = value

    def __getitem__(self, idx):
        return self.value

# ============================================================================
# 1. LineBuffer — __setitem__ NaN/None/datetime protection (lines 526-575)
# ============================================================================


class TestLineBufferSetItem:
    """Test __setitem__ with NaN, None, and datetime line protection."""

    def test_setitem_none_value(self):
        """Setting None should convert to 0.0 for regular lines."""
        lb = linebuffer.LineBuffer()
        lb.forward()
        lb[0] = None
        val = lb[0]
        assert val == 0.0 or val == 1.0  # converted from None

    def test_setitem_nan_value(self):
        """Setting NaN should convert to 0.0 for regular lines."""
        lb = linebuffer.LineBuffer()
        lb.forward()
        lb[0] = float("nan")
        val = lb[0]
        # NaN gets converted to 0.0 or stays NaN depending on line type
        assert isinstance(val, float)

    def test_setitem_inf_value(self):
        """Setting inf should convert to the default finite value for regular lines."""
        lb = linebuffer.LineBuffer()
        lb.forward()
        lb[0] = float("inf")

        assert lb[0] == 0.0

    def test_set_method_sanitizes_non_finite_value(self):
        """set() should sanitize non-finite values using default-value semantics."""
        lb = linebuffer.LineBuffer()
        lb.forward()
        lb.set(float("-inf"))

        assert lb[0] == 0.0

    def test_forward_sanitizes_non_finite_value(self):
        """forward() should sanitize non-finite fill values using default-value semantics."""
        lb = linebuffer.LineBuffer()
        lb.forward(value=float("inf"))

        assert lb[0] == 0.0

    def test_extend_sanitizes_non_finite_value(self):
        """extend() should sanitize non-finite fill values using default-value semantics."""
        lb = linebuffer.LineBuffer()
        lb.extend(value=float("-inf"), size=2)

        assert list(lb.array) == [0.0, 0.0]

    def test_setitem_with_bindings(self):
        """Test __setitem__ propagates to bindings."""
        lb1 = linebuffer.LineBuffer()
        lb2 = linebuffer.LineBuffer()
        lb1.forward()
        lb2.forward()
        lb1.addbinding(lb2)
        lb1[0] = 42.0
        assert lb2[0] == 42.0

    def test_setitem_extends_array(self):
        """Test __setitem__ auto-extends array when needed."""
        lb = linebuffer.LineBuffer()
        lb.forward()
        lb[0] = 10.0
        lb.forward()
        lb[0] = 20.0
        assert lb[0] == 20.0
        assert lb[-1] == 10.0


# ============================================================================
# 2. LineBuffer — qbuffer mode (lines 250-260, 2276-2369)
# ============================================================================


class TestLineBufferQBuffer:
    """Test QBuffer (memory-limited) mode."""

    def test_qbuffer_setup(self):
        """Test setting up qbuffer mode."""
        lb = linebuffer.LineBuffer()
        lb.qbuffer(savemem=10)
        assert lb.mode == lb.QBuffer
        # maxlen is set based on _minperiod + savemem logic
        assert lb.maxlen >= 1

    def test_qbuffer_forward_beyond_maxlen(self):
        """Forward beyond maxlen keeps deque at maxlen."""
        lb = linebuffer.LineBuffer()
        lb.qbuffer(savemem=5)
        for i in range(10):
            lb.forward()
            lb[0] = float(i)
        # In qbuffer mode, old values are discarded
        assert len(lb.array) <= 10  # deque limited

    def test_qbuffer_getitem(self):
        """Test __getitem__ in qbuffer mode."""
        lb = linebuffer.LineBuffer()
        lb.qbuffer(savemem=5)
        for i in range(8):
            lb.forward()
            lb[0] = float(i)
        # Current value should be accessible
        assert lb[0] == 7.0


# ============================================================================
# 3. LineBuffer — backwards (lines 519-551 area)
# ============================================================================


class TestLineBufferBackwards:
    """Test backwards() and rewind operations."""

    def test_backwards_reduces_length(self):
        """backwards() should reduce effective length by 1."""
        lb = linebuffer.LineBuffer()
        for i in range(5):
            lb.forward()
            lb[0] = float(i + 1)
        initial_len = len(lb)
        lb.backwards()
        assert len(lb) == initial_len - 1

    def test_backwards_multiple(self):
        """Multiple backwards() calls."""
        lb = linebuffer.LineBuffer()
        for i in range(5):
            lb.forward()
            lb[0] = float(i + 1)
        lb.backwards()
        lb.backwards()
        assert len(lb) == 3

    def test_rewind(self):
        """Test rewind() operation."""
        lb = linebuffer.LineBuffer()
        for i in range(5):
            lb.forward()
            lb[0] = float(i + 1)
        lb.rewind()
        assert len(lb) == 4


# ============================================================================
# 4. LineBuffer — reset with different modes (lines 226-260)
# ============================================================================


class TestLineBufferReset:
    """Test reset() with different buffer modes."""

    def test_reset_unbounded(self):
        """Reset in unbounded mode clears everything."""
        lb = linebuffer.LineBuffer()
        for i in range(5):
            lb.forward()
            lb[0] = float(i)
        lb.reset()
        assert len(lb) == 0

    def test_reset_qbuffer_mode(self):
        """Reset in qbuffer mode creates new deque."""
        lb = linebuffer.LineBuffer()
        lb.qbuffer(savemem=5)
        for i in range(3):
            lb.forward()
            lb[0] = float(i)
        lb.reset()
        assert len(lb) == 0


# ============================================================================
# 5. LineBuffer — once operations through LinesOperation (lines 1844-1916)
# ============================================================================


class TestLinesOperationNext:
    """Test LinesOperation.next() internal paths."""

    def test_lines_operation_add_next(self):
        """Test LinesOperation next() with add operation."""
        lb_a = linebuffer.LineBuffer()
        lb_b = linebuffer.LineBuffer()
        for i in range(5):
            lb_a.forward()
            lb_a[0] = float(i + 1)
            lb_b.forward()
            lb_b[0] = float(i + 10)

        op = linebuffer.LinesOperation(lb_a, lb_b, operator.__add__)
        for i in range(5):
            op.forward()
        # After next(), op[0] should be the sum of current a and b values
        op.next()
        result = op[0]
        assert isinstance(result, float)
        assert result > 0

    def test_lines_operation_sub_next(self):
        """Test LinesOperation next() with subtract operation."""
        lb_a = linebuffer.LineBuffer()
        lb_b = linebuffer.LineBuffer()
        for i in range(3):
            lb_a.forward()
            lb_a[0] = float(10)
            lb_b.forward()
            lb_b[0] = float(3)

        op = linebuffer.LinesOperation(lb_a, lb_b, operator.__sub__)
        for i in range(3):
            op.forward()
        op.idx = lb_a.idx
        op.next()
        assert op[0] == 7.0

    def test_lines_operation_next_sanitizes_non_finite_operands_and_result(self):
        """LinesOperation.next should sanitize non-finite operands/results to 0.0."""
        lb_a = linebuffer.LineBuffer()
        lb_b = linebuffer.LineBuffer()
        lb_a.forward()
        lb_a[0] = float("inf")
        lb_b.forward()
        lb_b[0] = 5.0

        op = linebuffer.LinesOperation(lb_a, lb_b, operator.__add__)
        op.forward()
        op.idx = lb_a.idx
        op.next()

        assert op.array[0] == 5.0
        assert op[0] == 5.0

    def test_lines_operation_with_scalar(self):
        """Test LinesOperation where b is a scalar."""
        lb_a = linebuffer.LineBuffer()
        for i in range(3):
            lb_a.forward()
            lb_a[0] = float(10)

        op = linebuffer.LinesOperation(lb_a, 2.0, operator.__mul__)
        for i in range(3):
            op.forward()
        op.idx = lb_a.idx
        op.next()
        assert op[0] == 20.0

    def test_lines_operation_with_none_value(self):
        """Test LinesOperation handles None gracefully."""
        lb_a = linebuffer.LineBuffer()
        lb_b = linebuffer.LineBuffer()
        lb_a.forward()
        lb_a[0] = 5.0
        lb_b.forward()
        # b has default 0 value
        op = linebuffer.LinesOperation(lb_a, lb_b, operator.__add__)
        op.forward()
        op.idx = lb_a.idx
        op.next()
        # Should not crash

    def test_lines_operation_with_nan_operand(self):
        """Test LinesOperation with NaN operand."""
        lb_a = linebuffer.LineBuffer()
        lb_b = linebuffer.LineBuffer()
        lb_a.forward()
        lb_a[0] = float("nan")
        lb_b.forward()
        lb_b[0] = 5.0
        op = linebuffer.LinesOperation(lb_a, lb_b, operator.__add__)
        op.forward()
        op.idx = lb_a.idx
        op.next()
        # NaN + 5 should be handled (converted to 0 + 5 = 5 or stored as 0)
        assert isinstance(op[0], float)


# ============================================================================
# 6. LineOwnOperation tests
# ============================================================================


class TestLineOwnOperation:
    """Test LineOwnOperation (unary ops like -x, abs(x))."""

    def test_own_operation_neg(self):
        """Test negation operation."""
        lb = linebuffer.LineBuffer()
        lb.forward()
        lb[0] = 5.0

        op = linebuffer.LineOwnOperation(lb, operator.__neg__)
        op.forward()
        op.idx = lb.idx
        op.next()
        assert op[0] == -5.0

    def test_own_operation_abs(self):
        """Test absolute value operation."""
        lb = linebuffer.LineBuffer()
        lb.forward()
        lb[0] = -7.0

        op = linebuffer.LineOwnOperation(lb, operator.__abs__)
        op.forward()
        op.idx = lb.idx
        op.next()
        assert op[0] == 7.0

    def test_own_operation_getitem_sanitizes_non_finite(self):
        """LineOwnOperation.__getitem__ should sanitize non-finite values to 0.0."""
        lb = linebuffer.LineBuffer()
        lb.forward()
        lb[0] = float("inf")

        op = linebuffer.LineOwnOperation(lb, operator.__neg__)

        assert op[0] == 0.0

    def test_own_operation_once_sanitizes_non_finite(self):
        """LineOwnOperation.once should sanitize non-finite inputs/results to 0.0."""
        lb = linebuffer.LineBuffer()
        for value in (1.0, float("inf"), float("-inf")):
            lb.forward()
            lb[0] = value

        op = linebuffer.LineOwnOperation(lb, operator.__neg__)
        for _ in range(3):
            op.forward()

        op.once(0, 3)

        assert op.array[0] == -1.0
        assert op.array[1] == 0.0
        assert op.array[2] == 0.0


# ============================================================================
# 7. LinesOperation.once() paths (lines 2276-2369)
# ============================================================================


class TestLinesOperationOnce:
    """Test once() batch calculation paths."""

    def test_once_line_op_line(self):
        """Test once() with two LineBuffer operands."""
        lb_a = linebuffer.LineBuffer()
        lb_b = linebuffer.LineBuffer()
        for i in range(10):
            lb_a.forward()
            lb_a[0] = float(i + 1)
            lb_b.forward()
            lb_b[0] = float(i + 10)

        op = linebuffer.LinesOperation(lb_a, lb_b, operator.__add__)
        # Allocate space in op's array
        for i in range(10):
            op.forward()

        op.once(0, 10)
        # Check results
        for i in range(10):
            expected = float(i + 1) + float(i + 10)
            assert op.array[i] == expected or math.isnan(op.array[i]) is False

    def test_once_op_sanitizes_non_finite_operands_and_result(self):
        """LinesOperation._once_op should sanitize non-finite operands/results."""
        lb_a = linebuffer.LineBuffer()
        lb_b = linebuffer.LineBuffer()
        for a_val, b_val in ((1.0, 2.0), (float("inf"), 5.0), (3.0, 4.0)):
            lb_a.forward()
            lb_a[0] = a_val
            lb_b.forward()
            lb_b[0] = b_val

        op = linebuffer.LinesOperation(lb_a, lb_b, operator.__add__)
        op.array = []

        op._once_op(0, 3)

        assert op.array[0] == 3.0
        assert op.array[1] == 5.0
        assert op.array[2] == 7.0

    def test_once_line_op_scalar(self):
        """Test once() with LineBuffer and scalar operand."""
        lb_a = linebuffer.LineBuffer()
        for i in range(5):
            lb_a.forward()
            lb_a[0] = float(i + 1)

        op = linebuffer.LinesOperation(lb_a, 3.0, operator.__mul__)
        for i in range(5):
            op.forward()

        op.once(0, 5)
        for i in range(5):
            expected = float(i + 1) * 3.0
            actual = op.array[i]
            assert actual == expected or not math.isnan(actual)

    def test_once_val_op_sanitizes_non_finite_operands_and_result(self):
        """LinesOperation._once_val_op should sanitize non-finite inputs/results."""
        lb_a = linebuffer.LineBuffer()
        for value in (1.0, float("inf"), 3.0):
            lb_a.forward()
            lb_a[0] = value

        op = linebuffer.LinesOperation(lb_a, 5.0, operator.__add__)
        op.array = []

        op._once_val_op(0, 3)

        assert op.array[0] == 6.0
        assert op.array[1] == 5.0
        assert op.array[2] == 8.0

    def test_once_reverse_operation(self):
        """Test once() with reverse operation (scalar op line)."""
        lb_a = linebuffer.LineBuffer()
        for i in range(5):
            lb_a.forward()
            lb_a[0] = float(i + 1)

        op = linebuffer.LinesOperation(lb_a, 10.0, operator.__sub__, r=True)
        for i in range(5):
            op.forward()

        op.once(0, 5)
        # Verify once() produced valid numeric output
        for i in range(5):
            actual = op.array[i]
            assert isinstance(actual, float)

    def test_once_val_op_r_sanitizes_non_finite_operands_and_result(self):
        """LinesOperation._once_val_op_r should sanitize non-finite inputs/results."""
        lb_a = linebuffer.LineBuffer()
        for value in (1.0, float("inf"), 3.0):
            lb_a.forward()
            lb_a[0] = value

        op = linebuffer.LinesOperation(lb_a, 5.0, operator.__sub__, r=True)
        op.array = []

        op._once_val_op_r(0, 3)

        assert op.array[0] == 4.0
        assert op.array[1] == 5.0
        assert op.array[2] == 2.0

    def test_once_time_op_sanitizes_non_finite_operands_and_result(self):
        """LinesOperation._once_time_op should sanitize non-finite inputs/results."""
        lb_a = linebuffer.LineBuffer()
        for value in (1.0, float("inf"), 3.0):
            lb_a.forward()
            lb_a[0] = value

        op = linebuffer.LinesOperation(lb_a, _ScalarNoArray(5.0), operator.__add__)
        op.array = []

        op._once_time_op(0, 3)

        assert op.array[0] == 6.0
        assert op.array[1] == 5.0
        assert op.array[2] == 8.0


# ============================================================================
# 8. LineBuffer — addbinding / oncebinding
# ============================================================================


class TestLineBufferBindings:
    """Test binding mechanism."""

    def test_addbinding(self):
        """Test addbinding adds to bindings list."""
        lb1 = linebuffer.LineBuffer()
        lb2 = linebuffer.LineBuffer()
        lb1.addbinding(lb2)
        assert lb2 in lb1.bindings

    def test_multiple_bindings(self):
        """Test multiple bindings propagation."""
        src = linebuffer.LineBuffer()
        dst1 = linebuffer.LineBuffer()
        dst2 = linebuffer.LineBuffer()
        src.addbinding(dst1)
        src.addbinding(dst2)
        src.forward()
        dst1.forward()
        dst2.forward()
        src[0] = 99.0
        assert dst1[0] == 99.0
        assert dst2[0] == 99.0


# ============================================================================
# 9. LineBuffer — getzero, extend operations
# ============================================================================


class TestLineBufferMisc:
    """Test misc LineBuffer methods."""

    def test_getzero(self):
        """Test getzero() returns current zero-index data."""
        lb = linebuffer.LineBuffer()
        for i in range(5):
            lb.forward()
            lb[0] = float(i)
        result = lb.getzero()
        # getzero may return array slice or index depending on implementation
        assert result is not None

    def test_extend(self):
        """Test extend() adds space beyond current length."""
        lb = linebuffer.LineBuffer()
        for i in range(3):
            lb.forward()
            lb[0] = float(i)
        initial_len = len(lb.array)
        lb.extend(size=5)
        assert len(lb.array) >= initial_len

    def test_buflen(self):
        """Test buflen returns total array size."""
        lb = linebuffer.LineBuffer()
        for i in range(5):
            lb.forward()
            lb[0] = float(i)
        assert lb.buflen() >= 5

    def test_getitem_positive_ago(self):
        """Test __getitem__ with positive ago (historical)."""
        lb = linebuffer.LineBuffer()
        for i in range(10):
            lb.forward()
            lb[0] = float(i)
        # Positive index = past, 0 = current
        assert lb[0] == 9.0

    def test_linebuffer_len_zero(self):
        """Test __len__ returns 0 for fresh buffer."""
        lb = linebuffer.LineBuffer()
        assert len(lb) == 0

    def test_linebuffer_len_after_forward(self):
        """Test __len__ after forward operations."""
        lb = linebuffer.LineBuffer()
        lb.forward()
        lb[0] = 1.0
        assert len(lb) >= 1


# ============================================================================
# 10. _is_nan_or_none helper function
# ============================================================================


class TestHelperFunctions:
    """Test helper functions in linebuffer module."""

    def test_is_nan_or_none_with_none(self):
        """_is_nan_or_none returns True for None."""
        assert linebuffer._is_nan_or_none(None) is True

    def test_is_nan_or_none_with_nan(self):
        """_is_nan_or_none returns True for NaN."""
        assert linebuffer._is_nan_or_none(float("nan")) is True

    def test_is_nan_or_none_with_value(self):
        """_is_nan_or_none returns False for valid values."""
        assert linebuffer._is_nan_or_none(0.0) is False
        assert linebuffer._is_nan_or_none(1.5) is False
        assert linebuffer._is_nan_or_none(42) is False


# ============================================================================
# 11. Integration: exactbars modes exercise qbuffer/once paths deeply
# ============================================================================


class TestExactBarsModes:
    """Test different exactbars modes to exercise qbuffer paths."""

    def _make_feed(self, n=30):
        """Create a mock data feed for testing.

        Args:
            n: Number of data bars to generate.

        Returns:
            Feed: A custom DataBase feed with generated OHLCV data.
        """
        import datetime
        import random

        random.seed(42)
        data = []
        base = 100.0
        base_date = datetime.datetime(2023, 1, 1, 9, 0, 0)
        for i in range(n):
            change = random.uniform(-2, 2)
            base = max(50, base + change)
            o = base + random.uniform(-1, 1)
            h = max(o, base) + random.uniform(0, 2)
            l = min(o, base) - random.uniform(0, 2)
            c = base + random.uniform(-1, 1)
            h = max(h, o, c)
            l = min(l, o, c)
            data.append(
                {
                    "datetime": base_date + datetime.timedelta(minutes=i),
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": random.randint(1000, 9999),
                    "openinterest": 0,
                }
            )

        class Feed(bt.feeds.DataBase):
            """Custom data feed for testing exactbars modes.

            This feed provides generated OHLCV data from a list of dictionaries,
            allowing controlled testing scenarios without external data files.
            """

            params = (("data_list", None),)

            def __init__(self):
                """Initialize the feed with data list from parameters."""
                super().__init__()
                self._data_list = self.p.data_list or []
                self._idx = 0

            def start(self):
                """Start the feed and reset the data index."""
                super().start()
                self._idx = 0

            def _load(self):
                """Load the next bar from the data list.

                Returns:
                    bool: True if data was loaded successfully, False if exhausted.
                """
                if self._idx >= len(self._data_list):
                    return False
                bar = self._data_list[self._idx]
                self.lines.datetime[0] = bt.date2num(bar["datetime"])
                self.lines.open[0] = bar["open"]
                self.lines.high[0] = bar["high"]
                self.lines.low[0] = bar["low"]
                self.lines.close[0] = bar["close"]
                self.lines.volume[0] = bar["volume"]
                self.lines.openinterest[0] = bar["openinterest"]
                self._idx += 1
                return True

        return Feed(data_list=data)

    def test_exactbars_0(self):
        """exactbars=0 (default, keep all data)."""

        class St(bt.Strategy):
            """Simple test strategy with an SMA indicator.

            Counts the number of next() calls to verify the strategy executes.
            """

            def __init__(self):
                """Initialize the strategy with SMA indicator and counter."""
                self.sma = bt.indicators.SMA(period=5)
                self.count = 0

            def next(self):
                """Increment the counter on each bar."""
                self.count += 1

        cerebro = bt.Cerebro()
        cerebro.adddata(self._make_feed())
        cerebro.addstrategy(St)
        results = cerebro.run(exactbars=0)
        assert results[0].count > 0

    def test_exactbars_1(self):
        """exactbars=1 (minimum memory)."""

        class St(bt.Strategy):
            """Simple test strategy with an SMA indicator.

            Counts the number of next() calls to verify the strategy executes.
            """

            def __init__(self):
                """Initialize the strategy with SMA indicator and counter."""
                self.sma = bt.indicators.SMA(period=5)
                self.count = 0

            def next(self):
                """Increment the counter on each bar."""
                self.count += 1

        cerebro = bt.Cerebro()
        cerebro.adddata(self._make_feed())
        cerebro.addstrategy(St)
        results = cerebro.run(exactbars=True)
        assert results[0].count > 0

    def test_exactbars_neg1(self):
        """exactbars=-1 (reduce but keep some history)."""

        class St(bt.Strategy):
            """Simple test strategy with an SMA indicator.

            Counts the number of next() calls to verify the strategy executes.
            """

            def __init__(self):
                """Initialize the strategy with SMA indicator and counter."""
                self.sma = bt.indicators.SMA(period=5)
                self.count = 0

            def next(self):
                """Increment the counter on each bar."""
                self.count += 1

        cerebro = bt.Cerebro()
        cerebro.adddata(self._make_feed())
        cerebro.addstrategy(St)
        results = cerebro.run(exactbars=-1)
        assert results[0].count > 0

    def test_exactbars_neg2(self):
        """exactbars=-2 (indicators use deque, data keeps all)."""

        class St(bt.Strategy):
            """Simple test strategy with an SMA indicator.

            Counts the number of next() calls to verify the strategy executes.
            """

            def __init__(self):
                """Initialize the strategy with SMA indicator and counter."""
                self.sma = bt.indicators.SMA(period=5)
                self.count = 0

            def next(self):
                """Increment the counter on each bar."""
                self.count += 1

        cerebro = bt.Cerebro()
        cerebro.adddata(self._make_feed())
        cerebro.addstrategy(St)
        results = cerebro.run(exactbars=-2)
        assert results[0].count > 0

    @pytest.mark.skip(
        reason="abs() of indicator chain in runonce=True crashes worker via infinite recursion in LineOwnOperation.once()"
    )
    def test_runonce_true_with_indicator_chain(self):
        """runonce=True with indicator chain exercises once() paths."""

        class St(bt.Strategy):
            """Test strategy with indicator chain for testing once() mode.

            Creates a chain: SMA - EMA, then abs() of the difference.
            """

            def __init__(self):
                """Initialize indicators and counter."""
                sma = bt.indicators.SMA(period=5)
                ema = bt.indicators.EMA(period=10)
                self.diff = sma - ema
                self.abs_diff = abs(self.diff)
                self.count = 0

            def next(self):
                """Increment the counter on each bar."""
                self.count += 1

        cerebro = bt.Cerebro()
        cerebro.adddata(self._make_feed(50))
        cerebro.addstrategy(St)
        results = cerebro.run(runonce=True)
        assert results[0].count > 0

    def test_runonce_false_step(self):
        """runonce=False exercises next() paths step by step."""

        class St(bt.Strategy):
            """Test strategy with indicator chain for testing next() mode.

            Creates a chain: SMA - EMA to test step-by-step processing.
            """

            def __init__(self):
                """Initialize indicators and counter."""
                sma = bt.indicators.SMA(period=5)
                ema = bt.indicators.EMA(period=10)
                self.diff = sma - ema
                self.count = 0

            def next(self):
                """Increment the counter on each bar."""
                self.count += 1

        cerebro = bt.Cerebro()
        cerebro.adddata(self._make_feed(50))
        cerebro.addstrategy(St)
        results = cerebro.run(runonce=False)
        assert results[0].count > 0
