"""Test module for backtrader efficiency in time series mode"""

import time

import numpy as np
import pandas as pd

import backtrader as bt


class SmaStrategy(bt.Strategy):
    # params = (('short_window',10),('long_window',60))
    params = {"short_window": 10, "long_window": 60}

    def log(self, txt, dt=None):
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print("%s, %s" % (dt.isoformat(), txt))

    def __init__(self):
        # Typically used for calculating indicators or preloading data, and defining variables
        self.short_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.short_window)
        self.long_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.long_window)

    def next(self):
        # Simply log the closing price of the series from the reference
        # self.log(f"ICBC,{self.datas[0].datetime.date(0)},closing price:{self.datas[0].close[0]}")
        # Get current position size
        size = self.getposition(self.datas[0]).size
        value = self.broker.get_value()
        self.log(
            f"short_ma:{self.short_ma[0]},long_ma:{self.long_ma[0]},size={size},account value after current bar close:{value}"
        )
        # Go long
        if size == 0 and self.short_ma[0] > self.long_ma[0]:
            # Open position, calculate lots tradable under 1x leverage
            try:
                # Use next bar's opening price to calculate specific lot size
                lots = 0.1 * value / (self.datas[0].open[1])
            except IndexError:
                lots = 0.1 * value / (self.datas[0].close[0])
            self.buy(self.datas[0], size=lots)
        # Close long position
        if size > 0 and self.short_ma[0] < self.long_ma[0]:
            self.close(self.datas[0])

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            # Order has been submitted and accepted
            return
        if order.status == order.Rejected:
            self.log(f"order is rejected : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Margin:
            self.log(f"order need more margin : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Cancelled:
            self.log(f"order is concelled : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Partial:
            self.log(f"order is partial : order_ref:{order.ref}  order_info:{order.info}")
        # Check if an order has been completed
        # Attention: broker could reject order if not enougth cash
        if order.status == order.Completed:
            if order.isbuy():
                self.log(
                    "buy result : buy_price : {} , buy_cost : {} , commission : {}".format(
                        order.executed.price, order.executed.value, order.executed.comm
                    )
                )

            else:  # Sell
                self.log(
                    "sell result : sell_price : {} , sell_cost : {} , commission : {}".format(
                        order.executed.price, order.executed.value, order.executed.comm
                    )
                )

    def notify_trade(self, trade):
        # Output information when a trade is completed
        if trade.isclosed:
            self.log(
                "closed symbol is : {} , total_profit : {} , net_profit : {}".format(
                    trade.getdataname(), trade.pnl, trade.pnlcomm
                )
            )
            # self.trade_list.append([self.datas[0].datetime.date(0),trade.getdataname(),trade.pnl,trade.pnlcomm])

        if trade.isopen:
            self.log("open symbol is : {} , price : {} ".format(trade.getdataname(), trade.price))

    #
    # def stop(self):
    #     # Output information when strategy stops
    #     pass


def run_strategy(n_rows=1000):
    # Add cerebro
    cerebro = bt.Cerebro()
    # Add strategy
    cerebro.addstrategy(SmaStrategy)
    cerebro.broker.setcash(5000000.0)

    # Prepare data
    # Use numpy to generate n_rows of data, add 3 to avoid negative numbers as much as possible
    np.random.seed(1)
    data = pd.DataFrame(
        {
            i: np.random.randn(n_rows)
            for i in ["open", "high", "low", "close", "volume", "total_value"]
        }
    )
    data.index = pd.date_range("1/1/2012", periods=len(data), freq="5min")
    data = data + 3
    feed = bt.feeds.PandasDirectData(dataname=data)
    # Add contract data
    cerebro.adddata(feed, name="test")
    # Set contract properties
    # comm = ComminfoFuturesPercent(commission=0.0, margin=0.10, mult=10)
    # cerebro.broker.addcommissioninfo(comm, name="test")
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="_TotalValue")
    cerebro.addanalyzer(bt.analyzers.PyFolio)
    # Run backtest
    results = cerebro.run()
    # cerebro.plot()
    pyfoliozer = results[0].analyzers.getbyname("pyfolio")
    total_value = results[0].analyzers.getbyname("_TotalValue").get_analysis()
    total_value = pd.DataFrame([total_value]).T
    returns, positions, transactions, gross_lev = pyfoliozer.get_pf_items()
    # print(total_value)
    return total_value


if __name__ == "__main__":
    begin_time = time.perf_counter()
    total_value = run_strategy(n_rows=1000)
    end_time = time.perf_counter()
    print(f"Execution time:{end_time - begin_time}")
    print("Run result:", total_value.tail())
