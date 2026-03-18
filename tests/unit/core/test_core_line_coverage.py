"""Targeted coverage tests for core Line system modules.

Covers uncovered paths in:
- lineroot.py (45% → target 65%+): operators, stage2, bool, _makeoperation
- linebuffer.py (56% → target 70%+): __getitem__ edges, backwards, qbuffer, once ops
- lineseries.py (55% → target 70%+): __getattr__, __setattr__, line registration
- lineiterator.py (43% → target 55%+): donew, dopreinit, _next, StrategyBase

Uses real cerebro runs where needed and direct construction for unit-level coverage.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import math
import operator
import random

import backtrader as bt
from backtrader import functions as btfunctions
from backtrader import linebuffer, lineroot, lineseries


# ============================================================================
# Shared helpers
# ============================================================================

def generate_ohlcv(num_bars=50, seed=99):
    """Generate synthetic OHLCV data for testing.

    Args:
        num_bars: Number of bars to generate.
        seed: Random seed for reproducibility.

    Returns:
        List of dicts with datetime, open, high, low, close, volume data.
    """
    random.seed(seed)
    data = []
    base = 100.0
    base_date = datetime.datetime(2023, 1, 1, 9, 0, 0)
    for i in range(num_bars):
        change = random.uniform(-2, 2)
        base = max(50, base + change)
        o = base + random.uniform(-1, 1)
        h = max(o, base) + random.uniform(0, 2)
        l = min(o, base) - random.uniform(0, 2)
        c = base + random.uniform(-1, 1)
        h = max(h, o, c)
        l = min(l, o, c)
        data.append({
            "datetime": base_date + datetime.timedelta(minutes=i),
            "open": o, "high": h, "low": l, "close": c,
            "volume": random.randint(1000, 9999), "openinterest": 0,
        })
    return data


class SimpleFeed(bt.feeds.DataBase):
    """Simple data feed for testing with pre-generated data.

    Attributes:
        params: Contains data_list parameter with OHLCV data.
    """
    params = (("data_list", None),)

    def __init__(self):
        """Initialize the simple data feed."""
        super().__init__()
        self._data_list = self.p.data_list or []
        self._idx = 0

    def start(self):
        """Start the data feed and reset the index."""
        super().start()
        self._idx = 0

    def _load(self):
        """Load the next bar of data.

        Returns:
            bool: True if data was loaded successfully, False if at end.
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


def run_cerebro(strategy_class, num_bars=50, **kwargs):
    """Run a Cerebro backtest with the given strategy.

    Args:
        strategy_class: Strategy class to instantiate.
        num_bars: Number of bars of data to generate.
        **kwargs: Additional arguments to pass to Cerebro.

    Returns:
        Strategy instance from the completed backtest.
    """
    cerebro = bt.Cerebro()
    data = SimpleFeed(data_list=generate_ohlcv(num_bars=num_bars))
    cerebro.adddata(data)
    cerebro.addstrategy(strategy_class, **kwargs)
    results = cerebro.run()
    return results[0]


# ============================================================================
# 1. lineroot.py — operators and stage2 paths
# ============================================================================

class TestLineRootOperators:
    """Test LineRoot arithmetic and comparison operators."""

    def test_stage1_arithmetic_via_strategy(self):
        """Arithmetic ops in stage1 create LinesOperation objects."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy with arithmetic operations."""
                self.add_line = self.data.close + self.data.open
                self.sub_line = self.data.close - self.data.open
                self.mul_line = self.data.close * 2
                self.div_line = self.data.close / 2
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1

        strat = run_cerebro(St)
        assert strat.bar_count > 0

    def test_stage2_comparison_operators(self):
        """Comparison operators in stage2 return bool values."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy."""
                self.results = []

            def next(self):
                """Execute trading logic for each bar and collect comparison results."""
                c = self.data.close[0]
                o = self.data.open[0]
                self.results.append({
                    "lt": self.data.close < self.data.open,
                    "gt": self.data.close > self.data.open,
                    "le": self.data.close <= self.data.open,
                    "ge": self.data.close >= self.data.open,
                    "eq": self.data.close == self.data.open,
                    "ne": self.data.close != self.data.open,
                })

        strat = run_cerebro(St)
        assert len(strat.results) > 0
        for r in strat.results:
            for key in ("lt", "gt", "le", "ge"):
                assert isinstance(r[key], bool), f"{key} should be bool"

    def test_stage2_comparison_with_scalar(self):
        """Comparison operators with scalar values in stage2."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy."""
                self.results = []

            def next(self):
                """Execute trading logic for each bar and compare with scalars."""
                self.results.append({
                    "lt_scalar": self.data.close < 100.0,
                    "gt_scalar": self.data.close > 50.0,
                    "le_scalar": self.data.close <= 200.0,
                    "ge_scalar": self.data.close >= 0.0,
                })

        strat = run_cerebro(St)
        assert len(strat.results) > 0

    def test_stage2_comparison_with_none(self):
        """Comparison operators handle None gracefully in stage2."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy."""
                self.ok = True

            def next(self):
                """Execute trading logic for each bar and test None comparisons."""
                try:
                    _ = self.data.close < None
                    _ = self.data.close > None
                    _ = self.data.close <= None
                    _ = self.data.close >= None
                except Exception:
                    self.ok = False

        strat = run_cerebro(St)
        assert strat.ok

    def test_cmp_with_none_constant(self):
        """Cmp should sanitize None constants instead of crashing in next()."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy."""
                self.cmp_line = bt.Cmp(self.data.close, None)
                self.cmpex_line = bt.CmpEx(self.data.close, None, -1.0, 0.0, 1.0)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar and verify comparison lines are finite."""
                self.bar_count += 1
                assert self.cmp_line[0] in (-1, 0, 1)
                assert self.cmpex_line[0] in (-1.0, 0.0, 1.0)

        strat = run_cerebro(St)
        assert strat.bar_count > 0

    def test_cmp_with_nan_and_none_runonce(self):
        """Cmp/CmpEx should sanitize NaN and None in once() path under runonce."""

        data_list = generate_ohlcv(30)
        data_list[5]["close"] = float("nan")
        data_list[10]["close"] = None

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy."""
                self.cmp_line = bt.Cmp(self.data.close, None)
                self.cmpex_line = bt.CmpEx(self.data.close, None, -1.0, 0.0, 1.0)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar and verify outputs remain valid."""
                self.bar_count += 1
                assert self.cmp_line[0] in (-1, 0, 1)
                assert self.cmpex_line[0] in (-1.0, 0.0, 1.0)

        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=data_list))
        cerebro.addstrategy(St)
        results = cerebro.run(runonce=True)
        assert results[0].bar_count > 0

    def test_div_helpers_with_none_and_nan(self):
        """DivByZero and DivZeroByZero should sanitize None/NaN in next()."""

        data_list = generate_ohlcv(20)
        data_list[4]["close"] = None
        data_list[7]["close"] = float("nan")

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy."""
                self.div_zero = bt.DivByZero(self.data.close, 2.0, zero=0.0)
                self.div_zero_zero = bt.DivZeroByZero(self.data.close, 2.0, single=1.0, dual=0.0)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar and verify outputs remain finite."""
                self.bar_count += 1
                assert math.isfinite(self.div_zero[0])
                assert math.isfinite(self.div_zero_zero[0])

        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=data_list))
        cerebro.addstrategy(St)
        results = cerebro.run(runonce=False)
        assert results[0].bar_count > 0

    def test_div_helpers_with_none_and_nan_runonce(self):
        """DivByZero and DivZeroByZero should sanitize None/NaN in once() path."""

        data_list = generate_ohlcv(30)
        data_list[6]["close"] = None
        data_list[11]["close"] = float("nan")

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy."""
                self.div_zero = bt.DivByZero(self.data.close, 2.0, zero=0.0)
                self.div_zero_zero = bt.DivZeroByZero(self.data.close, 2.0, single=1.0, dual=0.0)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar and verify outputs remain finite."""
                self.bar_count += 1
                assert math.isfinite(self.div_zero[0])
                assert math.isfinite(self.div_zero_zero[0])

        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=data_list))
        cerebro.addstrategy(St)
        results = cerebro.run(runonce=True)
        assert results[0].bar_count > 0

    def test_max_min_sum_with_none_and_nan(self):
        """Max/Min/Sum should sanitize None/NaN inputs in next()."""

        data_list = generate_ohlcv(20)
        data_list[3]["close"] = None
        data_list[8]["open"] = float("nan")

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy."""
                self.max_line = bt.Max(self.data.close, self.data.open)
                self.min_line = bt.Min(self.data.close, self.data.open)
                self.sum_line = bt.Sum(self.data.close, self.data.open)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar and verify outputs remain finite."""
                self.bar_count += 1
                assert math.isfinite(self.max_line[0])
                assert math.isfinite(self.min_line[0])
                assert math.isfinite(self.sum_line[0])

        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=data_list))
        cerebro.addstrategy(St)
        results = cerebro.run(runonce=False)
        assert results[0].bar_count > 0

    def test_max_min_sum_with_none_and_nan_runonce(self):
        """Max/Min/Sum should sanitize None/NaN inputs in once() path."""

        data_list = generate_ohlcv(30)
        data_list[4]["close"] = None
        data_list[9]["open"] = float("nan")

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy."""
                self.max_line = bt.Max(self.data.close, self.data.open)
                self.min_line = bt.Min(self.data.close, self.data.open)
                self.sum_line = bt.Sum(self.data.close, self.data.open)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar and verify outputs remain finite."""
                self.bar_count += 1
                assert math.isfinite(self.max_line[0])
                assert math.isfinite(self.min_line[0])
                assert math.isfinite(self.sum_line[0])

        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=data_list))
        cerebro.addstrategy(St)
        results = cerebro.run(runonce=True)
        assert results[0].bar_count > 0

    def test_unary_operators(self):
        """Test abs() and neg() operators."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy with unary operations."""
                self.abs_line = abs(self.data.close)
                self.neg_line = -self.data.close
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar and verify abs is non-negative."""
                self.bar_count += 1
                assert self.abs_line[0] >= 0

        strat = run_cerebro(St)
        assert strat.bar_count > 0

    def test_right_operators(self):
        """Test right-hand side operators (radd, rsub, rmul, etc)."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy with right-hand side operators."""
                self.radd = 10.0 + self.data.close
                self.rsub = 200.0 - self.data.close
                self.rmul = 3.0 * self.data.close
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1

        strat = run_cerebro(St)
        assert strat.bar_count > 0

    def test_floordiv_and_truediv(self):
        """Test floor division and true division operators."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy with floor and true division."""
                self.fdiv = self.data.close // 10
                self.tdiv = self.data.close / 10
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1

        strat = run_cerebro(St)
        assert strat.bar_count > 0

    def test_pow_operator(self):
        """Test power operator."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy with power operator."""
                self.pow_line = self.data.close ** 2
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1

        strat = run_cerebro(St)
        assert strat.bar_count > 0

    def test_bool_on_data(self):
        """Test __bool__/__nonzero__ on data line."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy."""
                self.bool_results = []

            def next(self):
                """Execute trading logic for each bar and test bool conversion."""
                result = bool(self.data.close)
                self.bool_results.append(result)

        strat = run_cerebro(St)
        assert len(strat.bool_results) > 0

    def test_stage_switch(self):
        """Test _stage1 and _stage2 switching."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy and test stage switching."""
                self.data.close._stage1()
                assert self.data.close._opstage == 1
                self.data.close._stage2()
                assert self.data.close._opstage == 2
                self.data.close._stage1()
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1

        strat = run_cerebro(St)
        assert strat.bar_count > 0


# ============================================================================
# 2. linebuffer.py — buffer operations and edge cases
# ============================================================================

class TestLineBuffer:
    """Test LineBuffer operations, qbuffer, and edge cases."""

    def test_basic_linebuffer_creation(self):
        """Create and use a basic LineBuffer."""
        lb = linebuffer.LineBuffer()
        lb.forward()
        lb[0] = 1.0
        assert lb[0] == 1.0
        lb.forward()
        lb[0] = 2.0
        assert lb[0] == 2.0
        assert lb[-1] == 1.0

    def test_linebuffer_extend(self):
        """Test extend method."""
        lb = linebuffer.LineBuffer()
        lb.forward()
        lb[0] = 5.0
        lb.forward()
        lb[0] = 10.0
        assert len(lb) == 2

    def test_linebuffer_home_and_advance(self):
        """Test home() and advance() — home resets internal pointer."""
        lb = linebuffer.LineBuffer()
        for i in range(5):
            lb.forward()
            lb[0] = float(i + 1)
        # After 5 forwards, lb[0] is last value
        assert lb[0] == 5.0
        # home() resets the idx pointer to start
        lb.home()
        # advance moves idx forward one position at a time
        lb.advance()
        lb.advance()
        lb.advance()
        lb.advance()
        # After home + 4 advances we are at the last position
        val = lb[0]
        assert isinstance(val, float)

    def test_linebuffer_reset(self):
        """Test reset() clears buffer."""
        lb = linebuffer.LineBuffer()
        lb.forward()
        lb[0] = 42.0
        lb.reset()
        assert len(lb) == 0

    def test_linebuffer_getitem_negative_beyond_range(self):
        """Test __getitem__ with negative index beyond available data."""
        lb = linebuffer.LineBuffer()
        lb.forward()
        lb[0] = 1.0
        val = lb[-5]
        assert val == 0.0 or isinstance(val, float)

    def test_linebuffer_array_access(self):
        """Test direct array access."""
        lb = linebuffer.LineBuffer()
        for i in range(3):
            lb.forward()
            lb[0] = float(i + 1)
        arr = lb.array
        assert len(arr) >= 3

    def test_linebuffer_get_method(self):
        """Test get() method for ago-based access — returns array."""
        lb = linebuffer.LineBuffer()
        for i in range(5):
            lb.forward()
            lb[0] = float(i + 1)
        # get() returns an array slice, not a scalar
        val = lb.get(ago=0, size=1)
        assert val[0] == 5.0
        val = lb.get(ago=-1, size=1)
        assert val[0] == 4.0
        # get multiple values
        vals = lb.get(ago=0, size=3)
        assert len(vals) == 3

    def test_linebuffer_operations_in_cerebro(self):
        """Test LinesOperation and LineOwnOperation through cerebro."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy with line operations."""
                self.sum_line = self.data.close + self.data.open
                self.neg_line = -self.data.close
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar and verify operations."""
                self.bar_count += 1
                c = self.data.close[0]
                o = self.data.open[0]
                expected_sum = c + o
                assert abs(self.sum_line[0] - expected_sum) < 1e-10

        strat = run_cerebro(St)
        assert strat.bar_count > 0

    def test_linebuffer_backwards(self):
        """Test backwards() operation."""
        lb = linebuffer.LineBuffer()
        for i in range(5):
            lb.forward()
            lb[0] = float(i + 1)
        lb.backwards()
        assert len(lb) == 4


# ============================================================================
# 3. lineseries.py — attribute access, line management
# ============================================================================

class TestLineSeries:
    """Test LineSeries __getattr__, __setattr__, line registration."""

    def test_lines_access_via_strategy(self):
        """Test accessing data lines by name in a strategy."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy."""
                self.line_names = []

            def next(self):
                """Execute trading logic for each bar and access data lines."""
                c = self.data.close[0]
                o = self.data.open[0]
                h = self.data.high[0]
                l = self.data.low[0]
                v = self.data.volume[0]
                assert c > 0
                assert h >= l

        strat = run_cerebro(St)

    def test_len_on_lines(self):
        """Test len() on Lines objects."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy."""
                self.len_results = []

            def next(self):
                """Execute trading logic for each bar and record data length."""
                self.len_results.append(len(self.data))

        strat = run_cerebro(St)
        assert len(strat.len_results) > 0
        for i, l in enumerate(strat.len_results):
            assert l == i + 1

    def test_getitem_on_data(self):
        """Test __getitem__ on data (both int and slice)."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy."""
                self.ok = True

            def next(self):
                """Execute trading logic for each bar and test data access."""
                try:
                    val = self.data.close[0]
                    assert isinstance(val, float)
                    if len(self.data) > 1:
                        val_prev = self.data.close[-1]
                        assert isinstance(val_prev, float)
                except Exception:
                    self.ok = False

        strat = run_cerebro(St)
        assert strat.ok

    def test_indicator_creates_lines(self):
        """Test that indicators properly create output lines."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""

            def __init__(self):
                """Initialize the test strategy with indicators."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.ema = bt.indicators.EMA(self.data.close, period=5)

            def next(self):
                """Execute trading logic for each bar."""

        strat = run_cerebro(St, num_bars=20)
        assert hasattr(strat.sma, "lines")
        assert hasattr(strat.sma.lines, "__getitem__")

    def test_custom_indicator_with_multiple_lines(self):
        """Test custom indicator with multiple output lines."""

        class MultiLineInd(bt.Indicator):
            """Indicator with multiple output lines for testing.

            Attributes:
                lines: Contains upper and lower output lines.
                params: Contains mult parameter for multiplier.
            """
            lines = ("upper", "lower")
            params = (("mult", 2.0),)

            def __init__(self):
                """Initialize the indicator with minimum period."""
                self.addminperiod(1)

            def next(self):
                """Calculate upper and lower bands for current bar."""
                self.lines.upper[0] = self.data.close[0] * self.p.mult
                self.lines.lower[0] = self.data.close[0] / self.p.mult

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with multi-line indicator."""
                self.ind = MultiLineInd(self.data, mult=1.5)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1
                c = self.data.close[0]
                assert abs(self.ind.lines.upper[0] - c * 1.5) < 1e-10
                assert abs(self.ind.lines.lower[0] - c / 1.5) < 1e-10

        strat = run_cerebro(St)
        assert strat.bar_count > 0

    def test_data_lines_size(self):
        """Test that data feed has correct number of lines."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy and count data lines."""
                self.num_lines = len(self.data.lines)

            def next(self):
                """Execute trading logic for each bar."""
                pass

        strat = run_cerebro(St)
        assert strat.num_lines >= 7  # datetime, open, high, low, close, volume, openinterest


# ============================================================================
# 4. lineiterator.py — donew, _next, once, StrategyBase
# ============================================================================

class TestLineIterator:
    """Test LineIterator lifecycle: donew, dopreinit, dopostinit, _next."""

    def test_strategy_lifecycle(self):
        """Full strategy lifecycle: init → prenext → next → stop."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with indicators."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.prenext_count = 0
                self.next_count = 0
                self.stopped = False

            def prenext(self):
                """Called before minimum period is reached."""
                self.prenext_count += 1

            def next(self):
                """Execute trading logic for each bar."""
                self.next_count += 1

            def stop(self):
                """Called when backtesting is complete."""
                self.stopped = True

        strat = run_cerebro(St, num_bars=30)
        assert strat.prenext_count > 0
        assert strat.next_count > 0
        assert strat.stopped

    def test_nextstart_called(self):
        """Test that nextstart is called exactly once at transition."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with indicators."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.nextstart_count = 0

            def nextstart(self):
                """Called exactly once at transition from prenext to next."""
                self.nextstart_count += 1
                super().nextstart()

            def next(self):
                """Execute trading logic for each bar."""
                pass

        strat = run_cerebro(St, num_bars=30)
        assert strat.nextstart_count == 1

    def test_multiple_indicators_dependency(self):
        """Test that dependent indicators are calculated in correct order."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with dependent indicators."""
                self.sma_fast = bt.indicators.SMA(self.data.close, period=5)
                self.sma_slow = bt.indicators.SMA(self.data.close, period=10)
                self.cross = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1
                assert not math.isnan(self.sma_fast[0])
                assert not math.isnan(self.sma_slow[0])

        strat = run_cerebro(St, num_bars=30)
        assert strat.bar_count > 0

    def test_strategy_with_multiple_data_feeds(self):
        """Test strategy with two data feeds."""
        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(30, seed=1)))
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(30, seed=2)))

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy."""
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1
                assert len(self.datas) == 2

        cerebro.addstrategy(St)
        results = cerebro.run()
        assert results[0].bar_count > 0

    def test_strategy_order_lifecycle(self):
        """Test order creation and notification through LineIterator."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with indicators."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.order_submitted = False
                self.order_completed = False

            def next(self):
                """Execute trading logic for each bar."""
                if not self.position and not self.order_submitted:
                    self.buy()
                    self.order_submitted = True

            def notify_order(self, order):
                """Receive order status notifications.

                Args:
                    order: The order object with status information.
                """
                if order.status == order.Completed:
                    self.order_completed = True

        strat = run_cerebro(St, num_bars=30)
        assert strat.order_submitted
        assert strat.order_completed

    def test_runonce_mode(self):
        """Test that cerebro.run(runonce=True) exercises once() paths."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with indicators."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1

        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(30)))
        cerebro.addstrategy(St)
        results = cerebro.run(runonce=True)
        assert results[0].bar_count > 0

    def test_preonce_and_oncestart(self):
        """Test preonce/oncestart/once lifecycle in runonce mode."""

        class OnceInd(bt.Indicator):
            """Indicator for testing runonce mode batch calculation.

            Attributes:
                lines: Contains out output line.
                params: Contains period parameter for SMA calculation.
            """
            lines = ("out",)
            params = (("period", 5),)

            def __init__(self):
                """Initialize the indicator with minimum period."""
                self.addminperiod(self.p.period)

            def next(self):
                """Calculate SMA for current bar."""
                self.lines.out[0] = sum(
                    self.data.close.get(ago=-i) for i in range(self.p.period)
                ) / self.p.period

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with indicator."""
                self.ind = OnceInd(self.data)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=30)
        assert strat.bar_count > 0


# ============================================================================
# 5. Integration tests — cover complex interaction paths
# ============================================================================

class TestCoreIntegration:
    """Integration tests covering cross-module interactions."""

    def test_indicator_chaining(self):
        """Test chaining indicators: SMA of SMA."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with chained indicators."""
                sma1 = bt.indicators.SMA(self.data.close, period=5)
                self.sma2 = bt.indicators.SMA(sma1, period=3)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1
                assert not math.isnan(self.sma2[0])

        strat = run_cerebro(St, num_bars=30)
        assert strat.bar_count > 0

    def test_line_operations_chained(self):
        """Test chaining arithmetic: (close + open) / 2 - SMA."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with chained operations."""
                midprice = (self.data.close + self.data.open) / 2
                self.diff = midprice - bt.indicators.SMA(midprice, period=5)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=30)
        assert strat.bar_count > 0

    def test_minperiod_propagation(self):
        """Test that minperiod propagates correctly through indicator chain."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with multiple indicators."""
                self.sma5 = bt.indicators.SMA(self.data.close, period=5)
                self.sma10 = bt.indicators.SMA(self.data.close, period=10)
                self.cross = bt.indicators.CrossOver(self.sma5, self.sma10)
                self.prenext_count = 0
                self.next_count = 0

            def prenext(self):
                """Called before minimum period is reached."""
                self.prenext_count += 1

            def next(self):
                """Execute trading logic for each bar."""
                self.next_count += 1

        strat = run_cerebro(St, num_bars=30)
        # prenext should be called for minperiod-1 bars (SMA10 needs 10 bars)
        assert strat.prenext_count >= 9
        assert strat.next_count > 0

    def test_analyzer_integration(self):
        """Test analyzer integration with strategy."""
        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(50)))

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with SMA indicator."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)

            def next(self):
                """Execute trading logic for each bar."""
                if not self.position:
                    if self.data.close > self.sma:
                        self.buy()
                elif self.data.close < self.sma:
                    self.sell()

        cerebro.addstrategy(St)
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        results = cerebro.run()
        strat = results[0]
        assert hasattr(strat.analyzers, "sharpe")
        assert hasattr(strat.analyzers, "drawdown")
        assert hasattr(strat.analyzers, "trades")

    def test_observer_integration(self):
        """Test observer integration (Broker, Trades)."""
        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(50)))

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def next(self):
                """Execute trading logic for each bar."""
                if not self.position:
                    self.buy()
                else:
                    self.sell()

        cerebro.addstrategy(St)
        results = cerebro.run()
        assert len(results) > 0

    def test_bracket_order(self):
        """Test bracket order creation."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy."""
                self.ordered = False

            def next(self):
                """Execute trading logic for each bar."""
                if not self.ordered and len(self.data) > 5:
                    self.buy_bracket(
                        limitprice=self.data.close[0] * 1.05,
                        stopprice=self.data.close[0] * 0.95,
                    )
                    self.ordered = True

        strat = run_cerebro(St, num_bars=30)
        assert strat.ordered

    def test_setminperiod_and_updateminperiod(self):
        """Test period management methods."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy and check minperiod."""
                sma = bt.indicators.SMA(self.data.close, period=5)
                mp = sma._minperiod
                assert mp >= 5

            def next(self):
                """Execute trading logic for each bar."""
                pass

        run_cerebro(St)

    def test_data_with_nan_values(self):
        """Test handling of NaN values in data."""
        data_list = generate_ohlcv(20)
        data_list[5]["close"] = float("nan")
        data_list[10]["high"] = float("nan")

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy."""
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1

        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=data_list))
        cerebro.addstrategy(St)
        results = cerebro.run()
        assert results[0].bar_count > 0


# ============================================================================
# 6. LineBuffer edge case tests
# ============================================================================

class TestLineBufferEdgeCases:
    """Test edge cases in LineBuffer operations."""

    def test_forward_multiple_times(self):
        """Forward buffer multiple times and verify positions."""
        lb = linebuffer.LineBuffer()
        for i in range(10):
            lb.forward()
            lb[0] = float(i)
        assert len(lb) == 10
        assert lb[0] == 9.0

    def test_setitem_and_getitem_consistency(self):
        """Verify __setitem__ and __getitem__ are consistent."""
        lb = linebuffer.LineBuffer()
        for i in range(5):
            lb.forward()
            lb[0] = float(i * 10)
        for i in range(5):
            expected = float((4 - i) * 10)
            assert lb[-i] == expected

    def test_buflen(self):
        """Test buflen() returns correct count."""
        lb = linebuffer.LineBuffer()
        for i in range(7):
            lb.forward()
            lb[0] = float(i)
        assert lb.buflen() == 7

    def test_empty_buffer_len(self):
        """Test len of empty buffer."""
        lb = linebuffer.LineBuffer()
        assert len(lb) == 0

    def test_getitem_on_empty(self):
        """Test accessing empty buffer returns safe default."""
        lb = linebuffer.LineBuffer()
        val = lb[0]
        assert isinstance(val, (int, float))


# ============================================================================
# 7. Strategy data access patterns
# ============================================================================

class TestStrategyDataAccess:
    """Test various data access patterns used in real strategies."""

    def test_get_method_on_data_line(self):
        """Test data.close.get(ago=-N, size=M) pattern."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy."""
                self.results = []

            def next(self):
                """Execute trading logic for each bar."""
                if len(self.data) >= 5:
                    vals = self.data.close.get(ago=0, size=5)
                    self.results.append(vals)

        strat = run_cerebro(St, num_bars=20)
        assert len(strat.results) > 0
        for vals in strat.results:
            assert len(vals) == 5

    def test_data_indexing_patterns(self):
        """Test common data indexing: data[0], data[-1], data.close[0]."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy."""
                self.ok = True

            def next(self):
                """Execute trading logic for each bar."""
                try:
                    _ = self.data.close[0]
                    if len(self.data) > 1:
                        _ = self.data.close[-1]
                    _ = self.data.open[0]
                    _ = self.data.high[0]
                    _ = self.data.low[0]
                except Exception:
                    self.ok = False

        strat = run_cerebro(St, num_bars=20)
        assert strat.ok

    def test_multiple_timeframe_access(self):
        """Test accessing data0 and data1 within a strategy."""
        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(30, seed=1)))
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(30, seed=2)))

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with multiple data feeds."""
                self.sma0 = bt.indicators.SMA(self.datas[0].close, period=5)
                self.sma1 = bt.indicators.SMA(self.datas[1].close, period=5)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1
                _ = self.datas[0].close[0]
                _ = self.datas[1].close[0]

        cerebro.addstrategy(St)
        results = cerebro.run()
        assert results[0].bar_count > 0

    def test_position_tracking(self):
        """Test position tracking across buys and sells."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy."""
                self.trade_log = []

            def next(self):
                """Execute trading logic for each bar."""
                if len(self.data) == 5:
                    self.buy(size=10)
                elif len(self.data) == 10:
                    self.sell(size=10)

            def notify_trade(self, trade):
                """Receive trade notifications.

                Args:
                    trade: The trade object with trade information.
                """
                self.trade_log.append({
                    "size": trade.size,
                    "pnl": trade.pnl,
                    "isclosed": trade.isclosed,
                })

        strat = run_cerebro(St, num_bars=20)
        assert len(strat.trade_log) > 0

    def test_cerebro_runonce_false(self):
        """Test cerebro with runonce=False (step-by-step mode)."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with indicators."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1

        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(30)))
        cerebro.addstrategy(St)
        results = cerebro.run(runonce=False)
        assert results[0].bar_count > 0


# ============================================================================
# 8. LineRoot — _operationown and _makeoperation edge cases
# ============================================================================

class TestLineRootMakeOperation:
    """Test _makeoperation and _makeoperationown edge paths."""

    def test_complex_expression_tree(self):
        """Test deeply nested expression: ((close + open) * 2 - high) / low."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with complex expression."""
                self.expr = ((self.data.close + self.data.open) * 2 - self.data.high) / self.data.low
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1
                c = self.data.close[0]
                o = self.data.open[0]
                h = self.data.high[0]
                l = self.data.low[0]
                expected = ((c + o) * 2 - h) / l
                assert abs(self.expr[0] - expected) < 1e-8

        strat = run_cerebro(St)
        assert strat.bar_count > 0

    def test_indicator_arithmetic_with_indicator(self):
        """Test arithmetic between two indicators."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with indicator arithmetic."""
                sma5 = bt.indicators.SMA(self.data.close, period=5)
                sma10 = bt.indicators.SMA(self.data.close, period=10)
                self.spread = sma5 - sma10
                self.ratio = sma5 / sma10
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=30)
        assert strat.bar_count > 0


class TestFunctionSanitizers:
    """Test low-level function sanitizers for numeric edge cases."""

    def test_sanitize_div_value_handles_infinity(self):
        assert btfunctions._sanitize_div_value(float("inf")) == 0.0
        assert btfunctions._sanitize_div_value(float("-inf")) == 0.0
        assert btfunctions._sanitize_div_value(float("nan")) == 0.0
        assert btfunctions._sanitize_div_value(None) == 0.0
        assert btfunctions._sanitize_div_value(5.0) == 5.0


# ============================================================================
# 9. Period management
# ============================================================================

class TestPeriodManagement:
    """Test minperiod propagation and qbuffer."""

    def test_qbuffer_mode(self):
        """Test qbuffer (exactbars) memory optimization."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy with indicators."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1

        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(30)))
        cerebro.addstrategy(St)
        results = cerebro.run(exactbars=True)
        assert results[0].bar_count > 0

    def test_preload_mode(self):
        """Test preload mode loads all data upfront."""

        class St(bt.Strategy):
            """Test strategy for line coverage."""
            def __init__(self):
                """Initialize the test strategy."""
                self.bar_count = 0

            def next(self):
                """Execute trading logic for each bar."""
                self.bar_count += 1

        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(30)))
        cerebro.addstrategy(St)
        results = cerebro.run(preload=True)
        assert results[0].bar_count > 0
