import datetime
from cProfile import Profile

import numpy as np
import pandas as pd

import backtrader as bt


def generate_random_n_bar_df(n):
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
    # The bar data and timestamps are randomly generated. While such market conditions likely don't exist, this should not affect the reliability of test results
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
    # params = (('short_window',10),('long_window',60))
    params = {"short_window": 10, "long_window": 20}

    def log(self, txt, dt=None):
        """Function for logging information"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        # Typically used for calculating indicators, preloading data, or defining variables
        self.short_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.short_window)
        self.long_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.long_window)

    def next(self):
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
    prof = Profile()
    prof.enable()
    run_direct_data(1000000)
    prof.create_stats()
    prof.print_stats()
