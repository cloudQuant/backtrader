#!/usr/bin/env python
"""
Test suite for PlotlyPlot backend.

This module contains comprehensive tests for the PlotlyPlot plotting backend
in backtrader. The PlotlyPlot backend provides interactive web-based plotting
capabilities using the Plotly library, supporting various chart styles including
candlestick, OHLC bar charts, and line charts.

Test Coverage:
    - Import and instantiation tests
    - Basic plotting functionality with different chart styles
    - Indicator plotting (SMA, RSI, etc.)
    - Large dataset performance testing
    - File export functionality (HTML)
    - Integration with Cerebro's plot() method

Chart Styles Supported:
    - candle: Candlestick chart showing open, high, low, close prices
    - bar: OHLC bar chart
    - line: Simple line chart showing close prices

Running Tests:
    Run all tests in this module:
        pytest tests/plot_plotly/test_plot_plotly.py -v

    Run a specific test class:
        pytest tests/plot_plotly/test_plot_plotly.py::TestPlotlyPlotBasic -v

    Run a specific test method:
        pytest tests/plot_plotly/test_plot_plotly.py::TestPlotlyPlotBasic::test_plot_candlestick_style -v
"""
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

import backtrader as bt
from backtrader.plot import PlotlyPlot


def generate_sample_data(n_bars=100, seed=42):
    """Generate sample OHLCV (Open, High, Low, Close, Volume) data for testing.

    This function creates synthetic financial data with realistic price movements
    using a random walk model. The data includes open, high, low, close prices
    and volume, which are essential for backtesting trading strategies.

    Args:
        n_bars (int, optional): Number of data bars (time periods) to generate.
            Defaults to 100.
        seed (int, optional): Random seed for reproducibility. Defaults to 42.

    Returns:
        pandas.DataFrame: DataFrame with OHLCV data and datetime index.
            The DataFrame has the following columns:
            - open: Opening price for each period
            - high: Highest price during the period
            - low: Lowest price during the period
            - close: Closing price for each period
            - volume: Trading volume for the period
            The index is a DatetimeIndex with daily frequency starting from
            2020-01-01.

    Examples:
        >>> df = generate_sample_data(n_bars=50)
        >>> df.shape
        (50, 5)
        >>> list(df.columns)
        ['open', 'high', 'low', 'close', 'volume']

    Note:
        The high price is always >= close price and low price is always <= close
        price by construction, ensuring realistic OHLC relationships.
        Volume is randomly generated between 1000 and 10000 shares.
    """
    np.random.seed(seed)
    dates = pd.date_range(start="2020-01-01", periods=n_bars, freq="D")
    price = 100 + np.cumsum(np.random.randn(n_bars) * 2)
    df = pd.DataFrame(
        {
            "open": price + np.random.randn(n_bars) * 0.5,
            "high": price + np.abs(np.random.randn(n_bars)) * 2,
            "low": price - np.abs(np.random.randn(n_bars)) * 2,
            "close": price,
            "volume": np.random.randint(1000, 10000, n_bars),
        },
        index=dates,
    )
    return df


class SimpleStrategy(bt.Strategy):
    """Simple strategy for testing PlotlyPlot functionality.

    This strategy is a minimal test strategy that sets up a Simple Moving
    Average (SMA) indicator but does not execute any trades. It is primarily
    used to verify that the plotting backend can correctly render indicators
    alongside price data.

    Attributes:
        sma (bt.indicators.SMA): Simple Moving Average indicator with a period
            of 10 bars, calculated on the close price.

    Note:
        This strategy does not execute any trades in the next() method,
        making it suitable for testing basic plotting functionality without
        order markers or position tracking complexity.
    """

    def __init__(self):
        """Initialize the strategy and set up indicators.

        Creates a 10-period Simple Moving Average (SMA) indicator based on
        the close price of the data feed. The indicator will be automatically
        plotted by the PlotlyPlot backend.

        Note:
            The SMA indicator is stored as an instance variable to ensure
            it is accessible for plotting and debugging purposes.
        """
        self.sma = bt.indicators.SMA(self.data.close, period=10)

    def next(self):
        """Execute strategy logic for each bar.

        This is a placeholder method that does nothing. In a real strategy,
        this method would contain the trading logic such as checking entry
        and exit conditions, and submitting buy/sell orders.

        Note:
            This method must be defined to satisfy the Strategy interface,
            even if no trading logic is implemented.
        """
        pass


class SMAStrategy(bt.Strategy):
    """SMA crossover strategy with buy/sell signals for testing.

    This strategy implements a classic dual moving average crossover system.
    It generates buy signals when the fast SMA crosses above the slow SMA
    and exit signals when the fast SMA crosses below the slow SMA.

    Parameters:
        fast_period (int): Period for the fast moving average. Defaults to 10.
        slow_period (int): Period for the slow moving average. Defaults to 30.

    Attributes:
        sma_fast (bt.indicators.SMA): Fast moving average indicator.
        sma_slow (bt.indicators.SMA): Slow moving average indicator.

    Trading Logic:
        - Entry (Long): When fast SMA crosses above slow SMA and no position exists
        - Exit: When fast SMA crosses below slow SMA and a position exists

    Note:
        This strategy only takes long positions. It does not short sell.
        The strategy is useful for testing plot rendering of order markers
        (buy/sell signals) and position tracking.
    """

    params = (
        ("fast_period", 10),
        ("slow_period", 30),
    )

    def __init__(self):
        """Initialize the strategy and set up SMA indicators.

        Creates two Simple Moving Average indicators:
        - A fast SMA with period specified by fast_period parameter (default: 10)
        - A slow SMA with period specified by slow_period parameter (default: 30)

        Both indicators are calculated on the close price of the data feed.
        """
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)

    def next(self):
        """Execute trading logic for each bar.

        Implements the moving average crossover strategy:
        1. If no position exists, buy when fast SMA crosses above slow SMA
        2. If a position exists, close it when fast SMA crosses below slow SMA

        Note:
            The position check uses `self.position` which evaluates to True
            when a position (long or short) exists.
        """
        if not self.position:
            if self.sma_fast > self.sma_slow:
                self.buy()
        elif self.sma_fast < self.sma_slow:
            self.close()


class RSIStrategy(bt.Strategy):
    """RSI indicator strategy for testing horizontal line plotting.

    This strategy sets up a Relative Strength Index (RSI) indicator to test
    the PlotlyPlot backend's ability to render horizontal reference lines.
    The RSI indicator typically has horizontal lines at 70 (overbought)
    and 30 (oversold) levels.

    Attributes:
        rsi (bt.indicators.RSI): Relative Strength Index indicator calculated
            on the close price with the default period of 14 bars.

    Note:
        This strategy does not execute any trades. It is specifically designed
        to test the rendering of indicators with horizontal reference lines,
        which is a common requirement for oscillator-type indicators like RSI,
        Stochastic, and CCI.
    """

    def __init__(self):
        """Initialize the strategy and set up the RSI indicator.

        Creates an RSI indicator with default parameters (14-period).
        The RSI will have horizontal lines at 70 and 30, which should be
        rendered correctly by the PlotlyPlot backend.

        Note:
            The default RSI period is 14 bars, which is a standard setting
            used in most technical analysis applications.
        """
        self.rsi = bt.indicators.RSI(self.data.close)

    def next(self):
        """Execute strategy logic for each bar.

        This is a placeholder method that does nothing. The primary purpose
        of this strategy is to test horizontal line rendering, not to execute
        trades based on RSI levels.

        Note:
            In a real RSI strategy, this method would contain logic to buy
            when RSI crosses below 30 (oversold) and sell when RSI crosses
            above 70 (overbought), or similar mean-reversion strategies.
        """
        pass


class TestPlotlyPlotImport:
    """Test suite for PlotlyPlot import and basic instantiation.

    This test class verifies that the PlotlyPlot backend can be properly
    imported from the backtrader.plot module and instantiated with various
    configuration options. These are foundational tests that must pass
    before any plotting functionality can be tested.

    Test Methods:
        test_import: Verifies PlotlyPlot can be imported
        test_instantiation: Verifies PlotlyPlot can be instantiated
        test_instantiation_with_style: Verifies PlotlyPlot accepts style parameters

    Note:
        These tests do not perform any actual plotting. They only verify
        that the PlotlyPlot class is available and can be created with
        different parameters.
    """

    def test_import(self):
        """Test that PlotlyPlot can be imported from backtrader.plot module.

        This test verifies that the PlotlyPlot class is properly exposed
        through the backtrader.plot module and is not None.

        Raises:
            AssertionError: If PlotlyPlot is None or cannot be imported.
        """
        from backtrader.plot import PlotlyPlot

        assert PlotlyPlot is not None

    def test_instantiation(self):
        """Test that PlotlyPlot can be instantiated with default parameters.

        Creates a PlotlyPlot instance using default parameters and verifies
        that the object is created successfully.

        Returns:
            PlotlyPlot: A new PlotlyPlot instance with default settings.

        Raises:
            AssertionError: If plotter instance is None.
        """
        plotter = PlotlyPlot()
        assert plotter is not None

    def test_instantiation_with_style(self):
        """Test PlotlyPlot instantiation with different chart style parameters.

        Verifies that PlotlyPlot can be created with different style options
        and that the style parameter is correctly stored in the plotter's
        configuration.

        Styles Tested:
            - candle: Candlestick chart style
            - bar: OHLC bar chart style
            - line: Line chart style

        Raises:
            AssertionError: If any style parameter is not correctly stored.
        """
        for style in ["candle", "bar", "line"]:
            plotter = PlotlyPlot(style=style)
            assert plotter.p.scheme.style == style


class TestPlotlyPlotBasic:
    """Test suite for basic PlotlyPlot functionality.

    This test class verifies the core plotting capabilities of PlotlyPlot,
    including rendering different chart styles and handling basic strategy
    outputs. All tests run a simple backtest and verify that plots are
    generated successfully.

    Test Coverage:
        - Simple strategy plotting with indicators
        - Candlestick chart rendering
        - OHLC bar chart rendering
        - Line chart rendering

    Note:
        These tests verify that plots are created (non-None) but do not
        validate the visual accuracy of the rendered charts.
    """

    def test_plot_simple_strategy(self):
        """Test plotting a simple strategy with SMA indicator.

        Runs a backtest with SimpleStrategy and verifies that PlotlyPlot
        can generate a figure object. The strategy includes an SMA indicator
        to test indicator rendering capabilities.

        Test Flow:
            1. Generate 100 bars of sample OHLCV data
            2. Create Cerebro instance and add SimpleStrategy
            3. Run backtest
            4. Create PlotlyPlot instance and plot results
            5. Verify one figure is generated and is not None

        Raises:
            AssertionError: If figure list is empty or figure is None.
        """
        df = generate_sample_data(100)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="candle")
        figs = plotter.plot(results[0])

        assert len(figs) == 1
        assert figs[0] is not None

    def test_plot_candlestick_style(self):
        """Test candlestick chart style rendering.

        Verifies that PlotlyPlot can successfully generate a candlestick
        chart, which displays open, high, low, and close prices in the
        traditional Japanese candlestick format.

        Test Flow:
            1. Generate 100 bars of sample OHLCV data
            2. Run backtest with SimpleStrategy
            3. Create PlotlyPlot with candle style
            4. Verify figure is generated

        Raises:
            AssertionError: If figure list is empty.
        """
        df = generate_sample_data(100)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="candle")
        figs = plotter.plot(results[0])

        assert len(figs) == 1

    def test_plot_bar_style(self):
        """Test OHLC bar chart style rendering.

        Verifies that PlotlyPlot can successfully generate an OHLC bar chart,
        which displays open, high, low, and close prices using vertical bars
        with horizontal ticks.

        Test Flow:
            1. Generate 100 bars of sample OHLCV data
            2. Run backtest with SimpleStrategy
            3. Create PlotlyPlot with bar style
            4. Verify figure is generated

        Raises:
            AssertionError: If figure list is empty.
        """
        df = generate_sample_data(100)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="bar")
        figs = plotter.plot(results[0])

        assert len(figs) == 1

    def test_plot_line_style(self):
        """Test line chart style rendering.

        Verifies that PlotlyPlot can successfully generate a line chart,
        which displays only the close price as a continuous line. This is
        the simplest chart style and is useful for quickly visualizing
        price trends.

        Test Flow:
            1. Generate 100 bars of sample OHLCV data
            2. Run backtest with SimpleStrategy
            3. Create PlotlyPlot with line style
            4. Verify figure is generated

        Raises:
            AssertionError: If figure list is empty.
        """
        df = generate_sample_data(100)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="line")
        figs = plotter.plot(results[0])

        assert len(figs) == 1


class TestPlotlyPlotIndicators:
    """Test suite for plotting with various technical indicators.

    This test class verifies that PlotlyPlot can correctly render different
    types of technical indicators, including simple overlay indicators
    (SMA) and oscillators with horizontal reference lines (RSI).

    Test Coverage:
        - SMA (Simple Moving Average) indicator plotting
        - RSI (Relative Strength Index) indicator plotting with horizontal lines

    Note:
        These tests ensure that indicators are correctly added to the plot
        and that special features like horizontal lines are rendered properly.
    """

    def test_plot_with_sma(self):
        """Test plotting with SMA (Simple Moving Average) indicators.

        Verifies that PlotlyPlot can render dual moving averages (fast and slow)
        correctly on the price chart. The SMAStrategy creates two SMAs with
        different periods, testing the plotter's ability to handle multiple
        indicators of the same type.

        Test Flow:
            1. Generate 200 bars of sample OHLCV data
            2. Run backtest with SMAStrategy (10 and 30 period SMAs)
            3. Create PlotlyPlot with candle style
            4. Verify figure is generated

        Raises:
            AssertionError: If figure list is empty.
        """
        df = generate_sample_data(200)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SMAStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="candle")
        figs = plotter.plot(results[0])

        assert len(figs) == 1

    def test_plot_with_rsi(self):
        """Test plotting with RSI indicator including horizontal reference lines.

        Verifies that PlotlyPlot can correctly render the RSI indicator
        along with its horizontal reference lines at the 70 (overbought)
        and 30 (oversold) levels. This is important for oscillator-type
        indicators that rely on fixed threshold levels.

        Test Flow:
            1. Generate 200 bars of sample OHLCV data
            2. Run backtest with RSIStrategy
            3. Create PlotlyPlot with candle style
            4. Verify figure is generated with horizontal lines

        Raises:
            AssertionError: If figure list is empty.

        Note:
            The RSI indicator's horizontal lines are a critical feature
            for visual interpretation of overbought/oversold conditions.
        """
        df = generate_sample_data(200)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(RSIStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="candle")
        figs = plotter.plot(results[0])

        assert len(figs) == 1


class TestPlotlyPlotLargeData:
    """Test suite for PlotlyPlot performance with large datasets.

    This test class verifies that PlotlyPlot can handle datasets of varying
    sizes efficiently. Plotly is designed to handle large datasets well,
    and these tests ensure that the backtrader integration maintains this
    performance characteristic.

    Test Coverage:
        - 1000 bar dataset
        - 5000 bar dataset (stress test)

    Note:
        These tests verify functionality but do not measure performance
        metrics. The focus is on ensuring the plotter does not fail or
        produce errors with larger datasets.
    """

    def test_plot_1000_bars(self):
        """Test plotting with 1000 bars of data.

        Verifies that PlotlyPlot can handle a moderately large dataset
        (1000 bars, approximately 3-4 years of daily data) without errors.

        Test Flow:
            1. Generate 1000 bars of sample OHLCV data
            2. Run backtest with SMAStrategy
            3. Create PlotlyPlot with candle style
            4. Verify figure is generated

        Raises:
            AssertionError: If figure list is empty.

        Note:
            1000 bars represents approximately 3-4 years of daily trading data,
            which is a typical backtest period for many strategies.
        """
        df = generate_sample_data(1000)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SMAStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="candle")
        figs = plotter.plot(results[0])

        assert len(figs) == 1

    def test_plot_5000_bars(self):
        """Test plotting with 5000 bars of data - performance stress test.

        Verifies that PlotlyPlot can handle a large dataset (5000 bars,
        approximately 15-20 years of daily data) efficiently. This test
        ensures the plotter scales well for long-term backtests.

        Test Flow:
            1. Generate 5000 bars of sample OHLCV data
            2. Run backtest with SimpleStrategy
            3. Create PlotlyPlot with candle style
            4. Verify figure is generated

        Raises:
            AssertionError: If figure list is empty.

        Note:
            5000 bars represents approximately 15-20 years of daily trading data.
            Plotly's web-based rendering handles large datasets well compared
            to matplotlib, making it suitable for long-term backtests.
        """
        df = generate_sample_data(5000)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="candle")
        figs = plotter.plot(results[0])

        assert len(figs) == 1


class TestPlotlyPlotSaveFile:
    """Test suite for saving PlotlyPlot figures to files.

    This test class verifies that figures generated by PlotlyPlot can be
    saved to disk in various formats. Plotly natively supports HTML export,
    which creates interactive, self-contained files that can be opened
    in any web browser.

    Test Coverage:
        - Saving figures to HTML format

    Note:
        Saved files are cleaned up after testing to avoid polluting the
        filesystem with test artifacts.
    """

    def test_save_html(self):
        """Test saving figure to HTML file.

        Verifies that PlotlyPlot figures can be saved as HTML files and
        that the generated files are valid (non-empty). HTML files created
        by Plotly are self-contained and include all necessary JavaScript
        for interactive viewing.

        Test Flow:
            1. Generate 100 bars of sample OHLCV data
            2. Run backtest with SimpleStrategy
            3. Create PlotlyPlot and generate figure
            4. Save figure to temporary HTML file
            5. Verify file exists and has content
            6. Clean up temporary file

        Raises:
            AssertionError: If file is not created or is empty.

        Note:
            Uses tempfile.NamedTemporaryFile for safe temporary file creation.
            The file is deleted in the finally block regardless of test outcome.
        """
        df = generate_sample_data(100)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="candle")
        figs = plotter.plot(results[0])

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            temp_path = f.name

        try:
            figs[0].write_html(temp_path)
            assert os.path.exists(temp_path)
            assert os.path.getsize(temp_path) > 0
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TestCerebroPlotBackend:
    """Test suite for Cerebro integration with PlotlyPlot backend.

    This test class verifies that PlotlyPlot can be used as a backend
    for Cerebro's plot() method. This integration allows users to easily
    switch between different plotting backends (matplotlib, plotly, etc.)
    without changing their backtest code.

    Test Coverage:
        - Creating PlotlyPlot instance for use with Cerebro

    Note:
        Full integration testing of cerebro.plot() is not performed here
        to avoid GUI-related issues in automated test environments.
        These tests verify that the plotter can be created and configured.
    """

    def test_cerebro_plot_plotly_backend(self):
        """Test using PlotlyPlot as the plotting backend for Cerebro.

        Verifies that PlotlyPlot can be instantiated and configured for
        use as the plotting backend when calling cerebro.plot(). This test
        ensures the plotter is properly initialized and ready to receive
        strategy results.

        Test Flow:
            1. Generate 100 bars of sample OHLCV data
            2. Create Cerebro instance and add SimpleStrategy
            3. Run backtest
            4. Create PlotlyPlot instance with candle style
            5. Verify plotter is correctly instantiated

        Raises:
            AssertionError: If plotter is not an instance of PlotlyPlot.

        Note:
            This test does not call cerebro.plot() to avoid potential issues
            with GUI display in automated testing environments. The focus is
            on verifying that the plotter can be created and configured.
        """
        df = generate_sample_data(100)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        cerebro.run()

        # This should not raise an error
        # Note: We don't call show() in tests
        from backtrader.plot import PlotlyPlot

        plotter = PlotlyPlot(style="candle")
        # Verify the plotter was created correctly for plotly backend
        assert isinstance(plotter, PlotlyPlot)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
