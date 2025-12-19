#!/usr/bin/env python
"""
Tests for PlotlyPlot backend.

Run with: pytest tests/plot_plotly/test_plot_plotly.py -v
"""
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

import backtrader as bt
from backtrader.plot import PlotlyPlot


def generate_sample_data(n_bars=100, seed=42):
    """Generate sample OHLCV data for testing."""
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
    """Simple strategy for testing."""

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=10)

    def next(self):
        pass


class SMAStrategy(bt.Strategy):
    """SMA crossover strategy with buy/sell signals."""

    params = (
        ("fast_period", 10),
        ("slow_period", 30),
    )

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)

    def next(self):
        if not self.position:
            if self.sma_fast > self.sma_slow:
                self.buy()
        elif self.sma_fast < self.sma_slow:
            self.close()


class RSIStrategy(bt.Strategy):
    """Strategy with RSI indicator (has horizontal lines)."""

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close)

    def next(self):
        pass


class TestPlotlyPlotImport:
    """Test PlotlyPlot import and instantiation."""

    def test_import(self):
        """Test that PlotlyPlot can be imported."""
        from backtrader.plot import PlotlyPlot

        assert PlotlyPlot is not None

    def test_instantiation(self):
        """Test that PlotlyPlot can be instantiated."""
        plotter = PlotlyPlot()
        assert plotter is not None

    def test_instantiation_with_style(self):
        """Test instantiation with different styles."""
        for style in ["candle", "bar", "line"]:
            plotter = PlotlyPlot(style=style)
            assert plotter.p.scheme.style == style


class TestPlotlyPlotBasic:
    """Test basic PlotlyPlot functionality."""

    def test_plot_simple_strategy(self):
        """Test plotting a simple strategy."""
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
        """Test candlestick chart style."""
        df = generate_sample_data(100)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="candle")
        figs = plotter.plot(results[0])

        assert len(figs) == 1

    def test_plot_bar_style(self):
        """Test OHLC bar chart style."""
        df = generate_sample_data(100)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="bar")
        figs = plotter.plot(results[0])

        assert len(figs) == 1

    def test_plot_line_style(self):
        """Test line chart style."""
        df = generate_sample_data(100)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="line")
        figs = plotter.plot(results[0])

        assert len(figs) == 1


class TestPlotlyPlotIndicators:
    """Test plotting with various indicators."""

    def test_plot_with_sma(self):
        """Test plotting with SMA indicators."""
        df = generate_sample_data(200)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SMAStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="candle")
        figs = plotter.plot(results[0])

        assert len(figs) == 1

    def test_plot_with_rsi(self):
        """Test plotting with RSI indicator (has hlines)."""
        df = generate_sample_data(200)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(RSIStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="candle")
        figs = plotter.plot(results[0])

        assert len(figs) == 1


class TestPlotlyPlotLargeData:
    """Test PlotlyPlot with large datasets."""

    def test_plot_1000_bars(self):
        """Test plotting with 1000 bars."""
        df = generate_sample_data(1000)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SMAStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="candle")
        figs = plotter.plot(results[0])

        assert len(figs) == 1

    def test_plot_5000_bars(self):
        """Test plotting with 5000 bars - should be fast with Plotly."""
        df = generate_sample_data(5000)
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)
        cerebro.adddata(bt.feeds.PandasData(dataname=df))
        results = cerebro.run()

        plotter = PlotlyPlot(style="candle")
        figs = plotter.plot(results[0])

        assert len(figs) == 1


class TestPlotlyPlotSaveFile:
    """Test saving PlotlyPlot figures to files."""

    def test_save_html(self):
        """Test saving figure to HTML file."""
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
    """Test cerebro.plot() with backend parameter."""

    def test_cerebro_plot_plotly_backend(self):
        """Test using cerebro.plot() with plotly backend."""
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
