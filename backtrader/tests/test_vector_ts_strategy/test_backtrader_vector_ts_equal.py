"""Test the efficiency of backtrader and ts on time series, and the performance improvement after rewriting specific functions with python, numba, and cython.

This module compares the performance and results of:
1. Traditional backtrader strategy execution
2. Time series (TS) strategy with Python engine
3. Time series (TS) strategy with Numba JIT compilation
4. Time series (TS) strategy with Cython compilation

The test uses a simple moving average crossover strategy to verify that all four
approaches produce equivalent results while measuring execution time differences.
"""

import time

import numpy as np
import pandas as pd

import backtrader as bt
from backtrader.comminfo import ComminfoFuturesPercent
from backtrader.vectors.ts import AlphaTs


class AlphaTs001(AlphaTs):
    """Alpha time series strategy implementation for testing.

    This class extends AlphaTs to provide a concrete implementation for testing
    the time series vectorized backtesting engine. The strategy implements a
    simple moving average crossover approach.

    Note:
        Currently this is a placeholder class that inherits from AlphaTs.
        The actual signal calculation logic is commented out but shows how
        to implement a moving average crossover strategy.

    Example:
        To calculate signals based on moving average crossover:
        - Calculate short-term moving average
        - Calculate long-term moving average
        - Generate signal: 1 when short MA >= long MA, 0 otherwise
    """

    # params = (('short_window',10),('long_window',60))
    # def cal_signal(self):
    #     short_ma = np.convolve(self.close_arr,
    #     np.ones(self.params["short_window"]),
    #     'valid') / self.params["short_window"]
    #     long_ma = np.convolve(self.close_arr,
    #     np.ones(self.params["long_window"]),
    #     'valid') / self.params["long_window"]
    #     signal_arr = np.where(short_ma>=long_ma,1,0)
    #     return signal_arr
    pass


def run_ts_strategy(n_rows=1000, engine="python"):
    """Run a time series strategy with the specified computation engine.

    This function generates synthetic market data, calculates moving average
    crossover signals, and executes a backtest using the AlphaTs001 strategy
    with the specified computation engine (python, numba, or cython).

    Args:
        n_rows (int, optional): Number of data rows to generate. Defaults to 1000.
        engine (str, optional): Computation engine to use. Must be one of:
            'python', 'numba', or 'cython'. Defaults to 'python".

    Returns:
        pandas.DataFrame: A DataFrame containing the total value over time
            with a single column named 'ts'.

    Note:
        The function uses a fixed random seed (1) to ensure reproducibility
        across multiple runs with the same parameters.

    Example:
        >>> total_value = run_ts_strategy(n_rows=10000, engine='numba')
        >>> print(total_value.head())
    """
    # Prepare data
    # Use numpy to generate n_rows of data
    np.random.seed(1)
    data = pd.DataFrame(
        {
            i: np.random.randn(n_rows)
            for i in ["open", "high", "low", "close", "volume", "total_value"]
        }
    )
    data.index = pd.date_range("1/1/2012", periods=len(data), freq="5min")
    data = data + 100
    # Set parameters
    params = {
        "short_window": 10,
        "long_window": 60,
        "commission": 0.0002,
        "init_value": 100000000,
        "percent": 0.01,
    }
    # Calculate moving averages
    data["short_ma"] = data["close"].rolling(params["short_window"]).mean()
    data["long_ma"] = data["close"].rolling(params["long_window"]).mean()
    # Calculate signals
    data["signal"] = np.where(data["short_ma"] >= data["long_ma"], 1.0, 0.0)
    #     print(data[data['signal']!=0])
    #     data.to_csv("d:/test/test_ts.csv")
    strategy = AlphaTs001(
        np.array(data.index),
        np.array(data["open"]),
        np.array(data["high"]),
        np.array(data["low"]),
        np.array(data["close"]),
        np.array(data["volume"]),
        params,
        signal_arr=np.array(data["signal"]),
        engine=engine,
    )
    total_value = strategy.run()
    total_value.columns = ["ts"]
    # print(total_value)
    return total_value


class SmaStrategy(bt.Strategy):
    """Simple Moving Average crossover strategy for backtrader.

    This strategy implements a classic moving average crossover trading system:
    - When the short-term MA crosses above the long-term MA, go long (buy)
    - When the short-term MA crosses below the long-term MA, close the position

    Attributes:
        params (dict): Strategy parameters containing:
            - short_window (int): Period for the short-term moving average (default: 10)
            - long_window (int): Period for the long-term moving average (default: 60)
        short_ma (bt.indicators.SMA): Short-term simple moving average indicator
        long_ma (bt.indicators.SMA): Long-term simple moving average indicator

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(SmaStrategy, short_window=10, long_window=60)
    """

    # params = (('short_window',10),('long_window',60))
    params = {"short_window": 10, "long_window": 60}

    def log(self, txt, dt=None):
        """Log a message with an optional timestamp.

        Args:
            txt (str): The message text to log.
            dt (datetime, optional): datetime object for the timestamp.
                If None, uses the current bar's datetime. Defaults to None.
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print("%s, %s" % (dt.isoformat(), txt))

    def __init__(self):
        """Initialize the strategy and set up indicators.

        This method is called once when the strategy is created. It sets up
        the moving average indicators that will be used for generating
        trading signals.
        """
        # Generally used for calculating indicators or preloading data, and defining variables
        self.short_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.short_window)
        self.long_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.long_window)

    def next(self):
        """Execute trading logic for the current bar.

        This method is called for each bar of data after all indicators have
        been calculated. It implements the moving average crossover logic:
        - Enter long when short MA crosses above long MA (with no position)
        - Close position when short MA crosses below long MA (with position)

        The position size is calculated based on 1% of account value divided
        by the contract price multiplied by the contract multiplier.
        """
        # Simply log the closing price of the series from the reference
        # self.log(f"ICBC,{self.datas[0].datetime.date(0)},closing price:{self.datas[0].close[0]}")
        # Get current position size
        size = self.getposition(self.datas[0]).size
        value = self.broker.get_value()
        #         self.log(f"short_ma:{self.short_ma[0]},long_ma:{self.long_ma[0]},size={size},account value after current bar closes:{value}")
        # Go long
        if size == 0 and self.short_ma[0] > self.long_ma[0]:
            # Open position, calculate the number of lots that can be traded under 1x leverage
            info = self.broker.getcommissioninfo(self.datas[0])
            symbol_multi = info.p.mult
            try:
                # Use the next bar's opening price to calculate the specific number of lots
                lots = 0.01 * value / (self.datas[0].open[1] * symbol_multi)
            except Exception as e:
                print("Exception", e)
                lots = 0.01 * value / (self.datas[0].close[0] * symbol_multi)
            self.buy(self.datas[0], size=lots)
        # Close long position
        if size > 0 and self.short_ma[0] < self.long_ma[0]:
            self.close(self.datas[0])


#     def notify_order(self, order):
#         if order.status in [order.Submitted, order.Accepted]:
#             # Order has been submitted and accepted
#             return
#         if order.status == order.Rejected:
#             self.log(f"order is rejected : order_ref:{order.ref}  order_info:{order.info}")
#         if order.status == order.Margin:
#             self.log(f"order need more margin : order_ref:{order.ref}  order_info:{order.info}")
#         if order.status == order.Cancelled:
#             self.log(f"order is cancelled : order_ref:{order.ref}  order_info:{order.info}")
#         if order.status == order.Partial:
#             self.log(f"order is partial : order_ref:{order.ref}  order_info:{order.info}")
#         # Check if an order has been completed
#         # Attention: broker could reject order if not enough cash
#         if order.status == order.Completed:
#             if order.isbuy():
#                 self.log("buy result : buy_price : {} , buy_cost : {} , commission : {}".format(
#                     order.executed.price, order.executed.value, order.executed.comm))

#             else:  # Sell
#                 self.log("sell result : sell_price : {} , sell_cost : {} , commission : {}".format(
#                     order.executed.price, order.executed.value, order.executed.comm))


#     def notify_trade(self, trade):
#         # Output information when a trade ends
#         if trade.isclosed:
#             self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
#                 trade.getdataname(), trade.pnl, trade.pnlcomm))
#             # self.trade_list.append([self.datas[0].datetime.date(0),trade.getdataname(),trade.pnl,trade.pnlcomm])

#         if trade.isopen:
#             self.log('open symbol is : {} , price : {} '.format(
#                 trade.getdataname(), trade.price))
#
# def stop(self):
#     # Output information when strategy stops
#     pass


def run_backtrader_strategy(n_rows=1000):
    """Run a backtrader strategy with synthetic market data.

    This function generates synthetic market data and executes a backtest using
    the traditional backtrader engine with the SmaStrategy. It sets up the
    cerebro engine, adds the strategy, data feed, and analyzers, then runs
    the backtest and returns the total value over time.

    Args:
        n_rows (int, optional): Number of data rows to generate. Defaults to 1000.

    Returns:
        pandas.DataFrame: A DataFrame containing the total value over time
            with a single column named 'backtrader'.

    Note:
        The function uses a fixed random seed (1) to ensure reproducibility
        and generates data that is offset by +100 to avoid negative values.

    Example:
        >>> total_value = run_backtrader_strategy(n_rows=10000)
        >>> print(total_value.head())
    """
    # Add cerebro
    cerebro = bt.Cerebro()
    # Add strategy
    cerebro.addstrategy(SmaStrategy)
    cerebro.broker.setcash(100000000.0)

    # Prepare data
    # Use numpy to generate n_rows of data, add 100 to data to avoid negative numbers as much as possible
    np.random.seed(1)
    data = pd.DataFrame(
        {
            i: np.random.randn(n_rows)
            for i in ["open", "high", "low", "close", "volume", "total_value"]
        }
    )
    data.index = pd.date_range("1/1/2012", periods=len(data), freq="5min")
    data = data + 100
    feed = bt.feeds.PandasDirectData(dataname=data)
    # Add contract data
    cerebro.adddata(feed, name="test")
    # Set contract properties
    comm = ComminfoFuturesPercent(commission=0.0002, margin=1, mult=1)
    cerebro.broker.addcommissioninfo(comm, name="test")
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="_TotalValue")
    cerebro.addanalyzer(bt.analyzers.PyFolio)
    # Run backtest
    results = cerebro.run()
    # cerebro.plot()
    pyfolio_result = results[0].analyzers.getbyname("pyfolio")
    total_value = results[0].analyzers.getbyname("_TotalValue").get_analysis()
    total_value = pd.DataFrame([total_value]).T
    returns, positions, transactions, _ = pyfolio_result.get_pf_items()
    # print(total_value)
    total_value.columns = ["backtrader"]
    return total_value


n_rows = 10000
begin_time = time.perf_counter()
backtrader_total_value = run_backtrader_strategy(n_rows=n_rows)
end_time = time.perf_counter()
print(f"backtrader execution time:{end_time - begin_time}")

begin_time = time.perf_counter()
ts_python_total_value = run_ts_strategy(n_rows=n_rows, engine="python")
end_time = time.perf_counter()
ts_python_total_value.columns = ["ts_python"]
print(f"ts_python execution time:{end_time - begin_time}")

begin_time = time.perf_counter()
ts_numba_total_value = run_ts_strategy(n_rows=n_rows, engine="numba")
end_time = time.perf_counter()
ts_numba_total_value.columns = ["ts_numba"]
print(f"ts_numba execution time:{end_time - begin_time}")

begin_time = time.perf_counter()
ts_cython_total_value = run_ts_strategy(n_rows=n_rows, engine="cython")
end_time = time.perf_counter()
ts_cython_total_value.columns = ["ts_cython"]
print(f"ts_cython execution time:{end_time - begin_time}")

df = pd.concat(
    [backtrader_total_value, ts_numba_total_value, ts_python_total_value, ts_cython_total_value],
    join="outer",
    axis=1,
)
# df = pd.concat([ts_numba_total_value,ts_python_total_value,ts_cython_total_value],join="outer",axis=1)
print(df.corr())
"""
backtrader execution time:218.7071305999998
ts_python execution time:1.6099043001886457
ts_numba execution time:0.35054199979640543
ts_cython execution time:0.351795099908486
            backtrader  ts_numba  ts_python  ts_cython
backtrader    1.000000  0.999998   0.999998   0.999998
ts_numba      0.999998  1.000000   1.000000   1.000000
ts_python     0.999998  1.000000   1.000000   1.000000
ts_cython     0.999998  1.000000   1.000000   1.000000
"""
# df.plot()
