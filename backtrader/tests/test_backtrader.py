"""Test module for backtrader performance and functionality.

This module contains test utilities and strategies for benchmarking and
validating backtrader performance with large datasets. It includes functions
for generating random price data and a simple moving average crossover strategy
for testing purposes.

Example:
    Run the performance test with 1 million bars:
        python backtrader/tests/test_backtrader.py
"""

import datetime
from cProfile import Profile

import numpy as np
import pandas as pd

import backtrader as bt


def generate_random_n_bar_df(n):
    """Generate a DataFrame with n bars of random OHLCV data.

    This function creates synthetic market data with random open, high, low,
    close, volume, and open interest values. The high and low prices are
    adjusted to ensure they represent the actual high and low of each bar.

    Args:
        n (int): Number of bars to generate.

    Returns:
        pandas.DataFrame: DataFrame with columns:
            - open: Opening price
            - high: Highest price (max of OHLC)
            - low: Lowest price (min of OHLC)
            - close: Closing price
            - volume: Trading volume
            - openinterest: Open interest
            Index contains datetime values starting from 1990-01-01 09:00:00.

    Note:
        The bar data and timestamps are randomly generated. While such market
        conditions likely don't exist in reality, this should not affect the
        reliability of test results as the purpose is performance testing.
    """
    start_datetime = datetime.datetime(1990, 1, 1, 9, 0, 0)
    np.random.seed(1)
    a = np.random.random(n)
    np.random.seed(2)
    b = np.random.random(n)
    np.random.seed(3)
    c = np.random.random(n)
    np.random.seed(4)
    d = np.random.random(n)
    np.random.seed(5)
    e = np.random.random(n)
    np.random.seed(6)
    f = np.random.random(n)

    result = [a, b, c, d, e, f]
    result_df = pd.DataFrame(result).T
    result_df.columns = ["open", "high", "low", "close", "volume", "openinterest"]
    result_df.index = pd.to_datetime(
        [start_datetime + datetime.timedelta(seconds=i) for i in list(range(n))]
    )
    result_df["high"] = result_df[["open", "high", "low", "close"]].max(axis=1)
    result_df["low"] = result_df[["open", "high", "low", "close"]].min(axis=1)
    return result_df


class DirectStrategy(bt.Strategy):
    """A simple moving average crossover trading strategy.

    This strategy implements a dual moving average crossover system that:
        - Opens a long position when the short MA crosses above the long MA
        - Opens a short position when the short MA crosses below the long MA
        - Closes positions when the crossover reverses

    Attributes:
        params (dict): Strategy parameters.
            - short_window (int): Period for the short moving average (default: 10)
            - long_window (int): Period for the long moving average (default: 20)
        short_ma (bt.indicators.SMA): Short-term simple moving average.
        long_ma (bt.indicators.SMA): Long-term simple moving average.

    Note:
        This is a test strategy used primarily for performance benchmarking
        rather than actual trading. It uses fixed position sizes (1 unit) for
        all trades.
    """

    # params = (('short_window',10),('long_window',60))
    params = {"short_window": 10, "long_window": 20}

    def log(self, txt, dt=None):
        """Log a message with an optional timestamp.

        Args:
            txt (str): The message to log.
            dt (datetime.datetime, optional): Specific datetime to use.
                Defaults to None, which uses the current bar's datetime.
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """Initialize the strategy by creating moving average indicators.

        This method is called once before the backtest starts. It creates
        the short and long simple moving averages that will be used for
        generating trading signals.
        """
        self.short_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.short_window)
        self.long_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.long_window)

    def next(self):
        """Execute trading logic for each bar.

        This method is called for every bar of data after the minimum period
        has been satisfied. It implements the moving average crossover logic:
            - Close long position when short MA crosses below long MA
            - Close short position when short MA crosses above long MA
            - Open long position when short MA crosses above long MA
            - Open short position when short MA crosses below long MA
        """
        # Simply log the closing price of the series from the reference
        # self.log(f"ICBC,{self.datas[0].datetime.date(0)},closing price:{self.datas[0].close[0]}")
        # self.log(f"short_ma:{self.short_ma[0]},long_ma:{self.long_ma[0]}")
        # Get current position size
        data = self.datas[0]
        size = self.getposition(data).size

        # Close long position
        if size > 0 and self.short_ma[0] < self.long_ma[0] and self.short_ma[-1] > self.long_ma[-1]:
            self.close(data, size=1)
        # Close short position
        if size < 0 and self.short_ma[0] > self.long_ma[0] and self.short_ma[-1] < self.long_ma[-1]:
            self.close(data, size=1)

        # Open long position
        if (
            size == 0
            and self.short_ma[0] > self.long_ma[0]
            and self.short_ma[-1] < self.long_ma[-1]
        ):
            self.buy(data, size=1)
        # Open short position
        if (
            size == 0
            and self.short_ma[0] < self.long_ma[0]
            and self.short_ma[-1] > self.long_ma[-1]
        ):
            self.sell(data, size=1)

        # self.log(f"close:{self.datas[0].close[0]},short_ma:{self.short_ma[0]},long_ma:{self.long_ma[0]}")


#     def notify_order(self, order):
#         if order.status in [order.Submitted, order.Accepted]:
#             # Order has been submitted and accepted
#             return
#         if order.status == order.Rejected:
#             self.log(f"order is rejected : order_ref:{order.ref}  order_info:{order.info}")
#         if order.status == order.Margin:
#             self.log(f"order need more margin : order_ref:{order.ref}  order_info:{order.info}")
#         if order.status == order.Cancelled:
#             self.log(f"order is concelled : order_ref:{order.ref}  order_info:{order.info}")
#         if order.status == order.Partial:
#             self.log(f"order is partial : order_ref:{order.ref}  order_info:{order.info}")
#         # Check if an order has been completed
#         # Attention: broker could reject order if not enougth cash
#         if order.status == order.Completed:
#             if order.isbuy():
#                 self.log("buy result : buy_price : {} , buy_cost : {} , commission : {}".format(
#                             order.executed.price,order.executed.value,order.executed.comm))

#             else:  # Sell
#                 self.log("sell result : sell_price : {} , sell_cost : {} , commission : {}".format(
#                             order.executed.price,order.executed.value,order.executed.comm))

#     def notify_trade(self, trade):
#         # Output information when a trade is completed
#         if trade.isclosed:
#             self.log('closed symbol is : {} , total_profit : {} , net_profit : {}' .format(
#                             trade.getdataname(),trade.pnl, trade.pnlcomm))
#         if trade.isopen:
#             self.log('open symbol is : {} , price : {} ' .format(
#                             trade.getdataname(),trade.price))


def run_direct_data(n):
    """Run a backtest with DirectStrategy on randomly generated data.

    This function sets up a complete backtesting environment with:
        - Randomly generated price data
        - DirectStrategy with default parameters
        - PandasDirectData feed
        - Commission of 0.05% (0.0005)
        - Initial capital of 100,000

    Args:
        n (int): Number of bars to generate for the backtest.

    Note:
        This function is primarily used for performance testing with large
        datasets (e.g., 1,000,000 bars). The final portfolio value is
        printed at the end of the run.
    """
    print("begin")

    df = generate_random_n_bar_df(n)
    df.index = pd.to_datetime(df.index)
    datetime_list = list(df.index)
    # Add cerebro
    cerebro = bt.Cerebro()
    # Add strategy
    cerebro.addstrategy(DirectStrategy)
    # Prepare data
    params = dict(
        fromdate=datetime_list[0],
        todate=datetime_list[-1],
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        dtformat=("%Y-%m-%d %H:%M:%S"),  # Date and time format
        tmformat=("%H:%M:%S"),  # Time format
    )

    feed = bt.feeds.PandasDirectData(dataname=df, **params)
    # Add contract data
    cerebro.adddata(feed, name="xxxxxx")
    cerebro.broker.setcommission(commission=0.0005)

    # Add initial cash
    cerebro.broker.setcash(100000.0)

    # Start running
    cerebro.run()

    print(f"end value is {cerebro.broker.getvalue()}")


if __name__ == "__main__":
    """Run performance profiling test on 1 million bars.

    When executed as a script, this module:
        1. Creates a profiler to measure performance
        2. Runs DirectStrategy on 1,000,000 randomly generated bars
        3. Prints profiling statistics showing execution time breakdown

    Example:
        python backtrader/tests/test_backtrader.py

    The output will show the final portfolio value and detailed profiling
    statistics indicating where time was spent during the backtest.
    """
    prof = Profile()
    prof.enable()
    run_direct_data(1000000)
    prof.create_stats()
    prof.print_stats()
