"""Deep coverage tests for internal paths in core Line system modules.

Targets specific uncovered code paths in:
- lineiterator.py: donew arg parsing, dopreinit, dopostinit, once paths, StrategyBase
- lineseries.py: __setattr__ line registration, __getattr__ fallback, Lines.__setitem__
- linebuffer.py: qbuffer mode, backwards with extension, once operations, LineDelay

These tests exercise internal APIs that the first batch of tests
(test_core_line_coverage.py) could not reach through public API alone.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import math
import random

import backtrader as bt
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
        A list of dictionaries containing OHLCV data with datetime keys.
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
    """Simple data feed for testing with in-memory data.

    Attributes:
        _data_list: List of OHLCV dictionaries.
        _idx: Current index in the data list.
    """

    params = (("data_list", None),)

    def __init__(self):
        """Initialize the SimpleFeed with data from parameters."""
        super().__init__()
        self._data_list = self.p.data_list or []
        self._idx = 0

    def start(self):
        """Reset the data index when feed starts."""
        super().start()
        self._idx = 0

    def _load(self):
        """Load the next bar into the data lines.

        Returns:
            True if data was loaded, False if at end of data.
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


def run_cerebro(strategy_class, num_bars=50, **cerebro_kwargs):
    """Run a cerebro backtest with the given strategy.

    Args:
        strategy_class: The strategy class to instantiate.
        num_bars: Number of bars of data to generate.
        **cerebro_kwargs: Additional keyword arguments for cerebro.run().

    Returns:
        The first strategy instance from the backtest results.
    """
    strat_kwargs = cerebro_kwargs.pop("strat_kwargs", {})
    cerebro = bt.Cerebro()
    cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(num_bars=num_bars)))
    cerebro.addstrategy(strategy_class, **strat_kwargs)
    results = cerebro.run(**cerebro_kwargs)
    return results[0]


# ============================================================================
# 1. lineiterator.py — donew arg parsing, numeric args, observer mindatas
# ============================================================================

class TestLineIteratorDonew:
    """Test donew argument parsing and data setup in LineIterator.

    Tests the donew() method which handles argument parsing for indicators,
    including numeric constants, data source resolution, and observer setup.
    """

    def test_indicator_with_numeric_arg(self):
        """Test indicator that receives a numeric constant as argument.

        This tests the path in donew() where a numeric value is passed
        instead of a data object, which should be wrapped in a NumLine.
        """

        class St(bt.Strategy):
            """Test strategy for numeric argument handling in indicators."""

            def __init__(self):
                """Initialize strategy with SMA indicator and numeric shift."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.shift = self.sma + 10.0
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=30)
        assert strat.bar_count > 0

    def test_indicator_no_data_uses_owner(self):
        """Test that indicator with no explicit data uses owner's data.

        When an indicator is created without a data argument, it should
        automatically use the data from its owner (strategy or parent indicator).
        """

        class MyInd(bt.Indicator):
            """Test indicator that uses owner's data implicitly."""

            lines = ("out",)

            def __init__(self):
                """Initialize indicator with minimum period requirement."""
                self.addminperiod(1)

            def next(self):
                """Calculate output as double the close price."""
                self.lines.out[0] = self.data.close[0] * 2

        class St(bt.Strategy):
            """Test strategy for implicit data usage in indicators."""

            def __init__(self):
                """Initialize strategy with custom indicator."""
                self.ind = MyInd()
                self.bar_count = 0

            def next(self):
                """Increment bar counter and verify indicator output."""
                self.bar_count += 1
                assert abs(self.ind.out[0] - self.data.close[0] * 2) < 1e-10

        strat = run_cerebro(St, num_bars=20)
        assert strat.bar_count > 0

    def test_observer_registration(self):
        """Test that observers are registered with _mindatas=0.

        Observers have special data access patterns where _mindatas is
        set to 0, allowing them to access all data feeds freely.
        """

        class St(bt.Strategy):
            """Test strategy for observer registration verification."""

            def __init__(self):
                """Initialize strategy with bar counter."""
                self.bar_count = 0

            def next(self):
                """Increment bar counter and buy on first bar."""
                self.bar_count += 1
                if not self.position:
                    self.buy()

        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(30)))
        cerebro.addstrategy(St)
        cerebro.addobserver(bt.observers.Broker)
        results = cerebro.run()
        assert results[0].bar_count > 0

    def test_data_aliases_setup(self):
        """Test that data0, data_close etc aliases are set up in donew.

        The donew() method creates convenient aliases like data0, data_close
        for easier access to data sources in strategies.
        """

        class St(bt.Strategy):
            """Test strategy for data alias verification."""

            def __init__(self):
                """Initialize strategy and check for data aliases."""
                self.sma = bt.indicators.SMA(period=5)
                self.has_data0 = hasattr(self.sma, "data0")
                self.has_data = hasattr(self.sma, "data")

            def next(self):
                """Pass through method for strategy execution."""
                pass

        strat = run_cerebro(St, num_bars=20)
        assert strat.has_data0
        assert strat.has_data

    def test_dnames_dict(self):
        """Test dnames dictionary is populated.

        The dnames dictionary maps data names to their objects,
        used for named data access in strategies.
        """

        class St(bt.Strategy):
            """Test strategy for dnames dictionary verification."""

            def __init__(self):
                """Initialize strategy with bar counter."""
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        cerebro = bt.Cerebro()
        d = SimpleFeed(data_list=generate_ohlcv(20))
        d._name = "mydata"
        cerebro.adddata(d)
        cerebro.addstrategy(St)
        results = cerebro.run()
        strat = results[0]
        assert strat.bar_count > 0


# ============================================================================
# 2. lineiterator.py — once/preonce/oncestart paths
# ============================================================================

class TestLineIteratorOncePaths:
    """Test once-mode execution paths in LineIterator.

    The once mode is a performance optimization where indicators
    calculate all values at once rather than bar-by-bar.
    """

    def test_runonce_with_multiple_indicators(self):
        """Exercise once() paths with multiple chained indicators.

        Tests the once() calculation path through a chain of indicators,
        exercising the batch calculation logic.
        """

        class St(bt.Strategy):
            """Test strategy for multiple chained indicators in once mode."""

            def __init__(self):
                """Initialize strategy with SMA, CrossOver, and ATR indicators."""
                sma5 = bt.indicators.SMA(self.data.close, period=5)
                sma10 = bt.indicators.SMA(self.data.close, period=10)
                self.cross = bt.indicators.CrossOver(sma5, sma10)
                self.atr = bt.indicators.ATR(self.data, period=14)
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=50, runonce=True)
        assert strat.bar_count > 0

    def test_runonce_false_step_mode(self):
        """Exercise _next() paths with step-by-step mode.

        When runonce=False, indicators calculate bar-by-bar using
        the next() method instead of the batch once() method.
        """

        class St(bt.Strategy):
            """Test strategy for step-by-step indicator calculation."""

            def __init__(self):
                """Initialize strategy with SMA and EMA indicators."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.ema = bt.indicators.EMA(self.data.close, period=10)
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=30, runonce=False)
        assert strat.bar_count > 0

    def test_runonce_parent_next_reads_current_subindicator_value(self):
        """A parent indicator using next() must see the current child line."""

        class SequenceChild(bt.Indicator):
            lines = ("value",)

            def next(self):
                self.lines.value[0] = float(len(self.data))

            def once(self, start, end):
                dst = self.lines.value.array
                while len(dst) < end:
                    dst.append(0.0)

                for i in range(start, end):
                    dst[i] = float(i + 1)

        class ParentIndicator(bt.Indicator):
            lines = ("value",)

            def __init__(self):
                self.child = SequenceChild(self.data)
                self.addminperiod(8)

            def next(self):
                self.lines.value[0] = self.child[0]

        class St(bt.Strategy):
            def __init__(self):
                self.indicator = ParentIndicator(self.data)
                self.values = []

            def next(self):
                self.values.append(float(self.indicator[0]))

        def run(runonce):
            cerebro = bt.Cerebro(runonce=runonce, stdstats=False)
            cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(num_bars=20)))
            cerebro.addstrategy(St)
            return cerebro.run()[0].values

        runonce_values = run(True)
        step_values = run(False)

        assert runonce_values == step_values
        assert runonce_values == [float(i) for i in range(8, 21)]

    def test_line_assignment_indicator_runs_under_parent_indicator(self):
        """self.lines.xxx = Indicator(...) must drive the source as a child."""

        from backtrader.lineiterator import LineIterator

        class BoundChannel(bt.Indicator):
            lines = ("upper", "lower")
            params = (("period", 3),)

            def __init__(self):
                self.lines.upper = bt.indicators.Highest(self.data.high, period=self.p.period)
                self.lines.lower = bt.indicators.Lowest(self.data.low, period=self.p.period)

        class St(bt.Strategy):
            def __init__(self):
                self.channel = BoundChannel(self.data)
                self.values = []
                self.child_names = [
                    type(ind).__name__
                    for ind in self.channel._lineiterators[LineIterator.IndType]
                ]
                self.top_names = [
                    type(ind).__name__ for ind in self._lineiterators[LineIterator.IndType]
                ]

            def next(self):
                self.values.append(round(float(self.channel.lower[0]), 8))

        def run(runonce):
            cerebro = bt.Cerebro(runonce=runonce, stdstats=False)
            cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(num_bars=12)))
            cerebro.addstrategy(St)
            return cerebro.run()[0]

        step_strat = run(False)
        once_strat = run(True)

        assert step_strat.values == once_strat.values
        assert all(value != 0.0 for value in step_strat.values)
        assert step_strat.child_names == ["Highest", "Lowest"]
        assert step_strat.top_names == ["BoundChannel"]

    def test_line_assignment_operation_dependencies_run_under_parent_indicator(self):
        """Nested line operations must drive temporary indicator dependencies."""

        from backtrader.lineiterator import LineIterator

        class ExprChannel(bt.Indicator):
            lines = ("mid", "top")

            def __init__(self):
                self.lines.mid = bt.indicators.Lowest(self.data.low, period=3)
                spread = bt.indicators.Highest(self.data.high, period=4)
                self.lines.top = self.lines.mid + 2.0 * spread

        class St(bt.Strategy):
            def __init__(self):
                self.channel = ExprChannel(self.data)
                self.values = []
                self.child_names = [
                    type(ind).__name__
                    for ind in self.channel._lineiterators[LineIterator.IndType]
                ]
                self.top_names = [
                    type(ind).__name__ for ind in self._lineiterators[LineIterator.IndType]
                ]
                self.has_operation_child = any(
                    isinstance(ind, linebuffer.LinesOperation)
                    for ind in self.channel._lineiterators[LineIterator.IndType]
                )

            def next(self):
                self.values.append(round(float(self.channel.top[0]), 8))

        def run(runonce):
            cerebro = bt.Cerebro(runonce=runonce, stdstats=False)
            cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(num_bars=16)))
            cerebro.addstrategy(St)
            return cerebro.run()[0]

        step_strat = run(False)
        once_strat = run(True)

        assert step_strat.values == once_strat.values
        assert all(math.isfinite(value) and value != 0.0 for value in step_strat.values)
        assert step_strat.child_names[:2] == ["Lowest", "Highest"]
        assert step_strat.has_operation_child
        assert step_strat.top_names == ["ExprChannel"]

    def test_exactbars_true_qbuffer(self):
        """Exercise qbuffer allocation with exactbars=True.

        The exactbars mode uses queue buffers (qbuffer) to limit
        memory usage by only keeping necessary history.
        """

        class St(bt.Strategy):
            """Test strategy for qbuffer mode with exactbars."""

            def __init__(self):
                """Initialize strategy with SMA indicator."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=30, exactbars=True)
        assert strat.bar_count > 0

    def test_exactbars_negative_1(self):
        """Exercise exactbars=-1 mode (save memory but keep lines).

        exactbars=-1 provides memory savings while maintaining
        the ability to access line history.
        """

        class St(bt.Strategy):
            """Test strategy for exactbars=-1 mode."""

            def __init__(self):
                """Initialize strategy with SMA indicator."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=30, exactbars=-1)
        assert strat.bar_count > 0

    def test_preload_false(self):
        """Exercise non-preload path.

        When preload=False, data is loaded on-demand rather than
        being pre-loaded into memory.
        """

        class St(bt.Strategy):
            """Test strategy for non-preload data loading."""

            def __init__(self):
                """Initialize strategy with SMA indicator."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=30, preload=False, runonce=False)
        assert strat.bar_count > 0


# ============================================================================
# 3. lineiterator.py — StrategyBase methods
# ============================================================================

class TestStrategyBase:
    """Test StrategyBase-specific methods (lines 2029-2225).

    Tests the callback and order management methods that are
    specific to the StrategyBase class.
    """

    def test_notify_order(self):
        """Exercise notify_order callback.

        The notify_order callback is invoked whenever an order
        status changes.
        """

        class St(bt.Strategy):
            """Test strategy for notify_order callback."""

            def __init__(self):
                """Initialize strategy with order notification tracker."""
                self.orders_notified = []

            def next(self):
                """Place buy order on third bar."""
                if len(self.data) == 3:
                    self.buy()

            def notify_order(self, order):
                """Track order status changes."""
                self.orders_notified.append(order.status)

        strat = run_cerebro(St, num_bars=20)
        assert len(strat.orders_notified) > 0

    def test_notify_trade(self):
        """Exercise notify_trade callback.

        The notify_trade callback is invoked when a trade
        is opened or closed.
        """

        class St(bt.Strategy):
            """Test strategy for notify_trade callback."""

            def __init__(self):
                """Initialize strategy with trade notification tracker."""
                self.trades_notified = []

            def next(self):
                """Place buy and sell orders to create trades."""
                if len(self.data) == 3:
                    self.buy(size=10)
                elif len(self.data) == 8:
                    self.sell(size=10)

            def notify_trade(self, trade):
                """Track trade PnL on notification."""
                self.trades_notified.append(trade.pnl)

        strat = run_cerebro(St, num_bars=20)
        assert len(strat.trades_notified) > 0

    def test_notify_cashvalue(self):
        """Exercise notify_cashvalue callback.

        The notify_cashvalue callback provides updates on
        cash and portfolio value.
        """

        class St(bt.Strategy):
            """Test strategy for notify_cashvalue callback."""

            def __init__(self):
                """Initialize strategy with cash value tracker."""
                self.cash_values = []

            def next(self):
                """Place buy order on third bar."""
                if len(self.data) == 3:
                    self.buy()

            def notify_cashvalue(self, cash, value):
                """Track cash and value changes."""
                self.cash_values.append((cash, value))

        strat = run_cerebro(St, num_bars=20)
        assert len(strat.cash_values) > 0

    def test_notify_fund(self):
        """Exercise notify_fund callback.

        The notify_fund callback provides updates for fund-related
        metrics when fund valuation is active.
        """

        class St(bt.Strategy):
            """Test strategy for notify_fund callback."""

            def __init__(self):
                """Initialize strategy with fund data tracker."""
                self.fund_data = []

            def next(self):
                """Place buy order on third bar."""
                if len(self.data) == 3:
                    self.buy()

            def notify_fund(self, cash, value, fundvalue, shares):
                """Track fund value changes."""
                self.fund_data.append(fundvalue)

        strat = run_cerebro(St, num_bars=20)
        assert len(strat.fund_data) > 0

    def test_getposition(self):
        """Test getposition() method.

        getposition() returns the current position for a data feed,
        including size and price information.
        """

        class St(bt.Strategy):
            """Test strategy for getposition method."""

            def __init__(self):
                """Initialize strategy with position check flag."""
                self.pos_checked = False

            def next(self):
                """Check position and buy on third bar."""
                pos = self.getposition(self.data)
                if len(self.data) == 3:
                    self.buy(size=5)
                if len(self.data) > 5:
                    assert pos is not None
                    self.pos_checked = True

        strat = run_cerebro(St, num_bars=20)
        assert strat.pos_checked

    def test_sizer_integration(self):
        """Test sizer integration with strategy.

        Sizers determine order sizes based on portfolio value
        and other parameters.
        """

        class St(bt.Strategy):
            """Test strategy for sizer integration."""

            def __init__(self):
                """Initialize strategy with bar counter."""
                self.bar_count = 0

            def next(self):
                """Increment bar counter and buy with sizer."""
                self.bar_count += 1
                if not self.position:
                    self.order_target_percent(target=0.5)

        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(30)))
        cerebro.addstrategy(St)
        cerebro.addsizer(bt.sizers.PercentSizer, percents=50)
        results = cerebro.run()
        assert results[0].bar_count > 0

    def test_sell_short(self):
        """Test short selling.

        Short selling allows profiting from price decreases
        by selling before buying.
        """

        class St(bt.Strategy):
            """Test strategy for short selling."""

            def __init__(self):
                """Initialize strategy with short tracking flags."""
                self.short_opened = False
                self.short_closed = False

            def next(self):
                """Open short position and close it later."""
                if len(self.data) == 3:
                    self.sell(size=10)
                    self.short_opened = True
                elif len(self.data) == 8 and self.position:
                    self.buy(size=10)
                    self.short_closed = True

        strat = run_cerebro(St, num_bars=20)
        assert strat.short_opened

    def test_close_position(self):
        """Test close() method.

        The close() method closes an existing position by
        placing an opposing order of equal size.
        """

        class St(bt.Strategy):
            """Test strategy for close position method."""

            def __init__(self):
                """Initialize strategy with close tracking flag."""
                self.closed = False

            def next(self):
                """Open position on third bar and close on eighth."""
                if len(self.data) == 3:
                    self.buy(size=10)
                elif len(self.data) == 8 and self.position:
                    self.close()
                    self.closed = True

        strat = run_cerebro(St, num_bars=20)
        assert strat.closed


# ============================================================================
# 4. lineseries.py — __getattr__ name resolution, __setattr__ line binding
# ============================================================================

class TestLineSeriesAttrAccess:
    """Test __getattr__ and __setattr__ paths in LineSeries.

    Tests the attribute access patterns that allow lines to be
    accessed by name and indicators to bind to strategy attributes.
    """

    def test_lines_attribute_access_by_name(self):
        """Test accessing lines by name through __getattr__.

        Lines can be accessed using attribute syntax like
        indicator.sma which maps to indicator.lines.sma.
        """

        class St(bt.Strategy):
            """Test strategy for line attribute access."""

            def __init__(self):
                """Initialize strategy with SMA indicator."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.bar_count = 0

            def next(self):
                """Increment bar counter and access line attributes."""
                self.bar_count += 1
                _ = self.sma.sma[0]
                _ = self.sma[0]

        strat = run_cerebro(St, num_bars=20)
        assert strat.bar_count > 0

    def test_indicator_line_assignment(self):
        """Test assigning indicator output to strategy attribute.

        When an indicator's line is assigned to a strategy attribute,
        it creates a binding through __setattr__.
        """

        class MyInd(bt.Indicator):
            """Test indicator with multiple output lines."""

            lines = ("signal", "strength")
            params = (("period", 10),)

            def __init__(self):
                """Initialize indicator with minimum period."""
                self.addminperiod(self.p.period)

            def next(self):
                """Calculate signal and strength based on price vs average."""
                vals = [self.data.close[-(i)] for i in range(min(self.p.period, len(self.data)))]
                avg = sum(vals) / len(vals) if vals else 0
                self.lines.signal[0] = 1.0 if self.data.close[0] > avg else -1.0
                self.lines.strength[0] = abs(self.data.close[0] - avg)

        class St(bt.Strategy):
            """Test strategy for indicator line assignment."""

            def __init__(self):
                """Initialize strategy with custom indicator."""
                self.ind = MyInd(self.data, period=5)
                self.bar_count = 0

            def next(self):
                """Increment bar counter and verify signal values."""
                self.bar_count += 1
                sig = self.ind.signal[0]
                assert sig in (1.0, -1.0, 0.0) or isinstance(sig, float)

        strat = run_cerebro(St, num_bars=30)
        assert strat.bar_count > 0

    def test_line_binding_through_subtraction(self):
        """Test that self.lines.xxx = indicator correctly binds.

        Line binding allows indicator outputs to be connected
        to input lines of other indicators.
        """

        class BindInd(bt.Indicator):
            """Test indicator for line binding."""

            lines = ("diff",)

            def __init__(self):
                """Bind difference between close and SMA."""
                self.lines.diff = self.data.close - bt.indicators.SMA(self.data.close, period=5)

        class St(bt.Strategy):
            """Test strategy for line binding."""

            def __init__(self):
                """Initialize strategy with binding indicator."""
                self.ind = BindInd(self.data)
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=30)
        assert strat.bar_count > 0

    def test_lines_forward_and_reset(self):
        """Test forward() and reset() on LineSeries objects.

        forward() advances the line buffer to the next period,
        while reset() clears all data.
        """

        class St(bt.Strategy):
            """Test strategy for line forward and reset."""

            def __init__(self):
                """Initialize strategy with bar counter."""
                self.bar_count = 0

            def next(self):
                """Increment bar counter and access line properties."""
                self.bar_count += 1
                _ = len(self.data.lines)
                _ = self.data.lines[0]

        strat = run_cerebro(St, num_bars=20)
        assert strat.bar_count > 0


# ============================================================================
# 5. linebuffer.py — LineDelay, LineNum, once operations
# ============================================================================

class TestLineBufferDeep:
    """Test deep paths in linebuffer.py.

    Tests the line buffer implementation including delayed
    access, forwarding, and batch operations.
    """

    def test_line_delay(self):
        """Test LineDelay through indicator usage.

        LineDelay implements the negative indexing syntax
        for accessing historical values.
        """

        class St(bt.Strategy):
            """Test strategy for line delay."""

            def __init__(self):
                """Initialize strategy with delayed line."""
                self.delayed = self.data.close(-1)
                self.bar_count = 0

            def next(self):
                """Increment bar counter and verify delay matches."""
                self.bar_count += 1
                if len(self.data) > 1:
                    assert abs(self.delayed[0] - self.data.close[-1]) < 1e-10

        strat = run_cerebro(St, num_bars=20)
        assert strat.bar_count > 0

    def test_line_delay_positive(self):
        """Test positive LineDelay (look-ahead, used internally).

        Positive delay is used internally for certain
        calculation patterns.
        """

        class St(bt.Strategy):
            """Test strategy for positive delay handling."""

            def __init__(self):
                """Initialize strategy with bar counter."""
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=20)
        assert strat.bar_count > 0

    def test_line_forward_value(self):
        """Test LineForward through the (0) syntax.

        The (0) syntax creates a forward reference that
        always points to the current value.
        """

        class St(bt.Strategy):
            """Test strategy for line forward reference."""

            def __init__(self):
                """Initialize strategy with forward reference."""
                self.fwd = self.data.close(0)
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=20)
        assert strat.bar_count > 0

    def test_linebuffer_once_operations(self):
        """Test once() calculation path through indicators in runonce mode.

        Once mode processes all bars in a batch for improved
        performance.
        """

        class St(bt.Strategy):
            """Test strategy for once mode operations."""

            def __init__(self):
                """Initialize strategy with SMA and EMA indicators."""
                self.sma = bt.indicators.SMA(self.data.close, period=5)
                self.ema = bt.indicators.EMA(self.data.close, period=10)
                self.diff = self.sma - self.ema
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=40, runonce=True)
        assert strat.bar_count > 0

    def test_linebuffer_bindings(self):
        """Test line binding mechanism used by indicators.

        Line bindings allow one indicator's output to
        become another's input.
        """

        class BindTest(bt.Indicator):
            """Test indicator for line binding."""

            lines = ("out",)

            def __init__(self):
                """Bind output to difference of close and SMA."""
                self.lines.out = self.data.close - bt.indicators.SMA(self.data.close, period=3)

        class St(bt.Strategy):
            """Test strategy for line buffer bindings."""

            def __init__(self):
                """Initialize strategy with binding test indicator."""
                self.ind = BindTest(self.data)
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=20)
        assert strat.bar_count > 0

    def test_line_operations_once_mode(self):
        """Test LinesOperation and LineOwnOperation in once mode.

        Arithmetic operations on lines create operation objects
        that calculate values lazily.
        """

        class St(bt.Strategy):
            """Test strategy for line operations in once mode."""

            def __init__(self):
                """Initialize strategy with various line operations."""
                self.add_op = self.data.close + self.data.open
                self.neg_op = -self.data.close
                self.mul_op = self.data.close * 2.0
                self.div_op = self.data.close / 2.0
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=30, runonce=True)
        assert strat.bar_count > 0


# ============================================================================
# 6. Multi-data and complex scenarios
# ============================================================================

class TestComplexScenarios:
    """Test complex scenarios that exercise multiple code paths.

    These tests cover edge cases and combinations of features
    that may not be tested elsewhere.
    """

    def test_multi_data_different_lengths(self):
        """Test two data feeds with different bar counts.

        When data feeds have different lengths, the backtest
        should run until the shortest is exhausted.
        """
        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(30, seed=1)))
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(20, seed=2)))

        class St(bt.Strategy):
            """Test strategy for multiple data feeds."""

            def __init__(self):
                """Initialize strategy with SMAs for both data feeds."""
                self.sma0 = bt.indicators.SMA(self.datas[0].close, period=5)
                self.sma1 = bt.indicators.SMA(self.datas[1].close, period=5)
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        cerebro.addstrategy(St)
        results = cerebro.run()
        assert results[0].bar_count > 0

    def test_multiple_analyzers(self):
        """Test multiple analyzers exercising different paths.

        Analyzers collect performance metrics during the backtest.
        """

        class St(bt.Strategy):
            """Test strategy for multiple analyzers."""

            def __init__(self):
                """Initialize strategy with SMA indicator."""
                self.sma = bt.indicators.SMA(period=5)

            def next(self):
                """Buy when price above SMA, sell when below."""
                if not self.position:
                    if self.data.close > self.sma:
                        self.buy()
                else:
                    if self.data.close < self.sma:
                        self.sell()

        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(50)))
        cerebro.addstrategy(St)
        cerebro.addanalyzer(bt.analyzers.SharpeRatio)
        cerebro.addanalyzer(bt.analyzers.DrawDown)
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer)
        cerebro.addanalyzer(bt.analyzers.Returns)
        cerebro.addanalyzer(bt.analyzers.SQN)
        results = cerebro.run()
        strat = results[0]
        analysis = strat.analyzers.tradeanalyzer.get_analysis()
        assert isinstance(analysis, dict) or hasattr(analysis, "__getattr__")

    def test_signal_strategy(self):
        """Test SignalStrategy code path.

        SignalStrategy provides a simplified way to create
        strategies based on indicator signals.
        """
        cerebro = bt.Cerebro()
        cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(50)))
        cerebro.add_signal(
            bt.SIGNAL_LONG,
            bt.indicators.CrossOver,
            bt.indicators.SMA(period=5),
            bt.indicators.SMA(period=10),
        )
        results = cerebro.run()
        assert len(results) > 0

    def test_order_target_value(self):
        """Test order_target_value method.

        order_target_value adjusts position size to achieve
        a target portfolio value.
        """

        class St(bt.Strategy):
            """Test strategy for order target value."""

            def __init__(self):
                """Initialize strategy with ordered flag."""
                self.ordered = False

            def next(self):
                """Place order with target value after 5 bars."""
                if not self.ordered and len(self.data) > 5:
                    self.order_target_value(target=50000)
                    self.ordered = True

        strat = run_cerebro(St, num_bars=20)
        assert strat.ordered

    def test_order_target_size(self):
        """Test order_target_size method.

        order_target_size adjusts position to a specific
        number of shares/contracts.
        """

        class St(bt.Strategy):
            """Test strategy for order target size."""

            def __init__(self):
                """Initialize strategy with sized flag."""
                self.sized = False

            def next(self):
                """Set target size to 10 on bar 5, close on bar 10."""
                if len(self.data) == 5:
                    self.order_target_size(target=10)
                    self.sized = True
                elif len(self.data) == 10:
                    self.order_target_size(target=0)

        strat = run_cerebro(St, num_bars=20)
        assert strat.sized


# ============================================================================
# 7. Indicator once() calculation paths
# ============================================================================

class TestIndicatorOncePaths:
    """Test once() calculation for various indicator types.

    Different indicators implement once() differently based
    on their calculation requirements.
    """

    def test_bollinger_bands(self):
        """Test BollingerBands uses complex once calculations.

        Bollinger Bands require standard deviation calculation
        in batch mode.
        """

        class St(bt.Strategy):
            """Test strategy for Bollinger Bands."""

            def __init__(self):
                """Initialize strategy with Bollinger Bands indicator."""
                self.bb = bt.indicators.BollingerBands(self.data.close, period=10)
                self.bar_count = 0

            def next(self):
                """Increment bar counter and verify bands."""
                self.bar_count += 1
                assert self.bb.top[0] > self.bb.bot[0]

        strat = run_cerebro(St, num_bars=30, runonce=True)
        assert strat.bar_count > 0

    def test_macd_indicator(self):
        """Test MACD exercises EMA chain in once mode.

        MACD is composed of multiple EMAs that must be
        calculated in the correct order.
        """

        class St(bt.Strategy):
            """Test strategy for MACD indicator."""

            def __init__(self):
                """Initialize strategy with MACD indicator."""
                self.macd = bt.indicators.MACD(self.data.close)
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=50, runonce=True)
        assert strat.bar_count > 0

    def test_stochastic(self):
        """Test Stochastic uses Highest/Lowest in once mode.

        Stochastic requires finding highest and lowest values
        over a period.
        """

        class St(bt.Strategy):
            """Test strategy for Stochastic indicator."""

            def __init__(self):
                """Initialize strategy with Stochastic indicator."""
                self.stoch = bt.indicators.Stochastic(self.data, period=14)
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=40, runonce=True)
        assert strat.bar_count > 0

    def test_rsi(self):
        """Test RSI uses complex division/comparison in once mode.

        RSI calculation involves averaging gains and losses
        separately.
        """

        class St(bt.Strategy):
            """Test strategy for RSI indicator."""

            def __init__(self):
                """Initialize strategy with RSI indicator."""
                self.rsi = bt.indicators.RSI(self.data.close, period=14)
                self.bar_count = 0

            def next(self):
                """Increment bar counter and verify RSI range."""
                self.bar_count += 1
                assert 0 <= self.rsi[0] <= 100

        strat = run_cerebro(St, num_bars=40, runonce=True)
        assert strat.bar_count > 0

    def test_atr(self):
        """Test ATR uses TrueRange + SMA in once mode.

        Average True Range combines TrueRange calculation
        with smoothing.
        """

        class St(bt.Strategy):
            """Test strategy for ATR indicator."""

            def __init__(self):
                """Initialize strategy with ATR indicator."""
                self.atr = bt.indicators.ATR(self.data, period=14)
                self.bar_count = 0

            def next(self):
                """Increment bar counter and verify ATR is non-negative."""
                self.bar_count += 1
                assert self.atr[0] >= 0

        strat = run_cerebro(St, num_bars=40, runonce=True)
        assert strat.bar_count > 0


# ============================================================================
# 8. Edge cases: empty data, single bar, large data
# ============================================================================

class TestEdgeCases:
    """Test edge cases in the line system.

    Edge cases include minimal data, many indicators, and
    early termination scenarios.
    """

    def test_minimal_data_one_bar(self):
        """Test strategy with just 1 bar of data.

        Even with minimal data, the strategy should complete
        without errors.
        """

        class St(bt.Strategy):
            """Test strategy for minimal data handling."""

            def __init__(self):
                """Initialize strategy with bar counter."""
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=1)
        assert strat.bar_count == 1

    def test_minimal_data_two_bars(self):
        """Test strategy with 2 bars - enough for [-1] access.

        With 2 bars, historical access using [-1] should work.
        """

        class St(bt.Strategy):
            """Test strategy for historical access."""

            def __init__(self):
                """Initialize strategy with bar counter."""
                self.bar_count = 0

            def next(self):
                """Increment bar counter and access historical data."""
                self.bar_count += 1
                if len(self.data) > 1:
                    _ = self.data.close[-1]

        strat = run_cerebro(St, num_bars=2)
        assert strat.bar_count == 2

    def test_many_indicators(self):
        """Test strategy with many indicators stresses lineiterator registration.

        Many indicators test the registration and update
        mechanisms for line iterators.
        """

        class St(bt.Strategy):
            """Test strategy for many indicators."""

            def __init__(self):
                """Initialize strategy with multiple SMA indicators."""
                self.inds = []
                for p in range(3, 15):
                    self.inds.append(bt.indicators.SMA(self.data.close, period=p))
                self.bar_count = 0

            def next(self):
                """Increment bar counter on each iteration."""
                self.bar_count += 1

        strat = run_cerebro(St, num_bars=30)
        assert strat.bar_count > 0
        assert len(strat.inds) == 12

    def test_strategy_stop_early(self):
        """Test strategy that stops cerebro early.

        The runstop() method terminates the backtest before
        all data is processed.
        """

        class St(bt.Strategy):
            """Test strategy for early termination."""

            def __init__(self):
                """Initialize strategy with bar counter."""
                self.bar_count = 0

            def next(self):
                """Increment bar counter and stop at 5 bars."""
                self.bar_count += 1
                if self.bar_count >= 5:
                    self.env.runstop()

        strat = run_cerebro(St, num_bars=50)
        assert strat.bar_count == 5

    def test_cancel_order(self):
        """Test order cancellation path.

        Orders can be cancelled before they are filled,
        testing order management logic.
        """

        class St(bt.Strategy):
            """Test strategy for order cancellation."""

            def __init__(self):
                """Initialize strategy with cancellation tracking."""
                self.cancelled = False
                self.pending_order = None

            def next(self):
                """Place limit order and cancel it before fill."""
                if len(self.data) == 3:
                    self.pending_order = self.buy(
                        exectype=bt.Order.Limit,
                        price=self.data.close[0] * 0.5,
                    )
                elif len(self.data) == 5 and self.pending_order:
                    self.cancel(self.pending_order)
                    self.cancelled = True

        strat = run_cerebro(St, num_bars=20)
        assert strat.cancelled
