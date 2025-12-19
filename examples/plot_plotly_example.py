#!/usr/bin/env python
"""
Example demonstrating the Plotly plotting backend for backtrader.

Usage:
    python plot_plotly_example.py

This will generate an interactive HTML chart that handles large datasets
much better than matplotlib.
"""
import datetime

import backtrader as bt


class SMAStrategy(bt.Strategy):
    """Simple SMA crossover strategy for demonstration."""

    params = (
        ("fast_period", 10),
        ("slow_period", 30),
    )

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        # Store buy/sell signals for plotting
        self._buysell = []

    # def notify_order(self, order):
    #     """Record completed orders for plotting."""
    #     if order.status == order.Completed:
    #         self._buysell.append({
    #             "datetime": self.data.datetime.datetime(0),
    #             "price": order.executed.price,
    #             "type": "buy" if order.isbuy() else "sell"
    #         })

    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()


def run_example():
    """Run the example with Plotly plotting."""
    # Create cerebro
    cerebro = bt.Cerebro()

    # Add strategy
    cerebro.addstrategy(SMAStrategy)

    # Alternative: generate random data for testing
    import pandas as pd
    import numpy as np

    # Generate sample data
    np.random.seed(42)
    dates = pd.date_range(start="2020-01-01", periods=500, freq="D")
    price = 100 + np.cumsum(np.random.randn(500) * 2)
    df = pd.DataFrame(
        {
            "open": price + np.random.randn(500) * 0.5,
            "high": price + np.abs(np.random.randn(500)) * 2,
            "low": price - np.abs(np.random.randn(500)) * 2,
            "close": price,
            "volume": np.random.randint(1000, 10000, 500),
        },
        index=dates,
    )

    # Use PandasData feed
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    # Set initial cash
    cerebro.broker.setcash(100000)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="total_value")  # For equity curve

    # Run
    print("Starting Portfolio Value: %.2f" % cerebro.broker.getvalue())
    results = cerebro.run()
    print("Final Portfolio Value: %.2f" % cerebro.broker.getvalue())

    # Plot using Plotly backend
    print("\nGenerating Plotly chart...")
    cerebro.plot(backend="plotly", style="candle")

    # You can also save to HTML
    # from backtrader.plot import PlotlyPlot
    # plotter = PlotlyPlot(style="candle")
    # figs = plotter.plot(results[0])
    # for i, fig in enumerate(figs):
    #     fig.write_html(f"backtrader_chart_{i}.html")


if __name__ == "__main__":
    run_example()
