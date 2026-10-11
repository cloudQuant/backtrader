#!/usr/bin/env python
"""Example demonstrating the Plotly plotting backend for backtrader.

This module demonstrates how to use the Plotly plotting backend with backtrader
to create interactive HTML charts for visualizing backtesting results. The Plotly
backend handles large datasets much more efficiently than matplotlib and provides
interactive features such as zooming, panning, and hovering for detailed inspection.

Usage:
    python plot_plotly_example.py

The example generates sample price data, runs a simple SMA crossover strategy,
and displays an interactive candlestick chart with indicators, trades, and
performance metrics.
"""
import datetime

import backtrader as bt


class SMAStrategy(bt.Strategy):
    """Simple Moving Average (SMA) crossover trading strategy.

    This strategy implements a classic dual SMA crossover approach where:
    - A buy signal is generated when the fast SMA crosses above the slow SMA
    - A sell signal is generated when the fast SMA crosses below the slow SMA

    The strategy only enters long positions and closes them when the crossover
    reverses. It does not take short positions.

    Attributes:
        sma_fast (bt.indicators.SMA): Fast moving average indicator.
        sma_slow (bt.indicators.SMA): Slow moving average indicator.
        crossover (bt.indicators.CrossOver): Crossover indicator that signals
            when fast SMA crosses slow SMA. Positive values indicate bullish
            crossover, negative values indicate bearish crossover.
        _buysell (list): List to store buy/sell signals for plotting (currently
            unused but kept for future implementation).
    """

    params = (
        ("fast_period", 10),
        ("slow_period", 30),
    )

    def __init__(self):
        """Initialize the SMA strategy with indicators.

        Creates two Simple Moving Average indicators with different periods
        and a CrossOver indicator to detect when they intersect.
        """
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        # Store buy/sell signals for plotting
        self._buysell = []

    def notify_order(self, order):
        """Handle order status updates and record completed trades.

        This method is called by backtrader whenever an order status changes.
        It can be used to track order execution for logging, plotting, or
        analysis purposes.

        Args:
            order (bt.Order): The order object with updated status information.
                Contains order details including status, price, and execution
                information.

        Note:
            This method is currently commented out but kept for reference.
            When enabled, it records completed orders with datetime, price,
            and type (buy/sell) for plotting purposes.
        """
        if order.status == order.Completed:
            self._buysell.append({
                "datetime": self.data.datetime.datetime(0),
                "price": order.executed.price,
                "type": "buy" if order.isbuy() else "sell"
            })

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        This method is called when a trade is closed. It can be used to log
        trade results, calculate performance metrics, or update tracking variables.

        Args:
            trade (bt.Trade): The trade object containing information about
                the completed trade, including entry and exit prices, profit/loss,
                and commission.
        """
        pass

    def next(self):
        """Execute trading logic for each bar.

        This method is called by backtrader for each bar of data after all
        indicators have been calculated. Implements the core trading logic:

        1. If not in a position:
           - Buy when fast SMA crosses above slow SMA (crossover > 0)
        2. If in a position:
           - Close position when fast SMA crosses below slow SMA (crossover < 0)

        The strategy uses a trend-following approach, entering long positions
        on bullish crossovers and exiting on bearish crossovers.
        """
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()

    def stop(self):
        """Called when the backtest is finished.

        This method is invoked after all data has been processed. It can be
        used to perform cleanup, log final results, or display summary statistics.

        Common uses include:
        - Printing final portfolio value
        - Logging total trades executed
        - Calculating and displaying performance metrics
        - Saving results to a file or database
        """
        pass


def run_example():
    """Run the Plotly plotting example with a sample SMA crossover strategy.

    This function demonstrates the complete workflow of:
    1. Creating a Cerebro engine instance
    2. Adding the SMA crossover strategy
    3. Generating synthetic OHLCV price data
    4. Setting up broker with initial cash
    5. Adding performance analyzers (Sharpe Ratio, DrawDown, Total Value)
    6. Running the backtest
    7. Generating an interactive Plotly chart

    The generated chart includes candlesticks, volume, SMAs, trades, and
    an equity curve. The chart opens in a browser window and supports
    interactive exploration.

    Raises:
        Exception: If there are errors during data generation, backtesting,
            or plotting. Common issues include missing dependencies (plotly),
            insufficient data, or invalid configuration.

    Note:
        The function uses a fixed random seed (42) for reproducible results.
        Adjust the seed or remove it for different random data each run.
    """
    # Create cerebro instance
    cerebro = bt.Cerebro()

    # Add strategy
    cerebro.addstrategy(SMAStrategy)

    # Alternative: generate random data for testing
    import pandas as pd
    import numpy as np

    # Generate sample data with 500 bars of OHLCV data
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

    # Use PandasData feed to load the generated data
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    # Set initial cash for the broker
    cerebro.broker.setcash(100000)

    # Add analyzers for performance metrics
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="total_value")  # For equity curve

    # Run the backtest
    print("Starting Portfolio Value: %.2f" % cerebro.broker.getvalue())
    results = cerebro.run()
    print("Final Portfolio Value: %.2f" % cerebro.broker.getvalue())

    # Plot using Plotly backend
    print("\nGenerating Plotly chart...")
    cerebro.plot(backend="plotly", style="candle")

    # You can also save to HTML file instead of displaying interactively
    # from backtrader.plot import PlotlyPlot
    # plotter = PlotlyPlot(style="candle")
    # figs = plotter.plot(results[0])
    # for i, fig in enumerate(figs):
    #     fig.write_html(f"backtrader_chart_{i}.html")


if __name__ == "__main__":
    run_example()
