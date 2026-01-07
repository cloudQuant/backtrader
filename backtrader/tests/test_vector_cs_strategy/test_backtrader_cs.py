"""Test the efficiency of backtrader running on cross-sectional data"""

import math

# from multiprocessing import Pool
import time

import numpy as np

# import numpy as np
import pandas as pd

# import os
import backtrader as bt

# from itertools import product
# from backtrader.vectors.cal_functions import get_symbol
from backtrader.comminfo import (  # Commission fees for futures trading, by percentage or fixed amount
    ComminfoFuturesPercent,
)


# Write backtrader strategy
class CloseMaCs(bt.Strategy):
    # Strategy author
    author = "yunjinqi"
    # Strategy parameters
    params = (("look_back_days", 40), ("hold_days", 70), ("percent", 0.3))

    # Log corresponding information
    def log(self, txt, dt=None):
        # Logging function fot this strategy
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print("{}, {}".format(dt.isoformat(), txt))

    # Initialize strategy data
    def __init__(self):
        # Number of bars run
        self.bar_num = 0
        # Calculate MA indicator
        self.data_factor = {
            d.name: bt.indicators.NewDiff(d, period=self.p.look_back_days) for d in self.datas
        }
        self.data_new_factor = {d.name: [] for d in self.datas}
        # Save signals
        self.signals = {"datetime": []}
        # Save returns
        self.returns = {"datetime": []}
        # Save trade count
        # self.trade_num = 0

    def prenext(self):
        # Since there are thousands of futures data with different trading dates,
        # they won't naturally enter next
        # Need to call next function in each prenext to run
        self.next()
        # pass

    def next(self):
        data = self.datas[0]
        self.current_datetime = bt.num2date(data.datetime[0])
        # Calculate factor and sort
        result = []
        for d in self.datas[1:]:
            d_datetime = bt.num2date(d.datetime[0])
            if d_datetime == self.current_datetime:
                my_factor = self.data_factor[d.name][0]
                # self.log(f"{d.name}, {my_factor}")
                if not math.isnan(my_factor):
                    # self.log(f"{d.name}, {my_factor}, {new_factor}")
                    # assert abs(my_factor - new_factor) < 0.1
                    result.append([d.name, my_factor])
        if len(result) == 0:
            self.bar_num = -1
        if self.bar_num % self.p.hold_days == 0 and len(result) > 0:
            # self.log(f"{self.bar_num}, result: {result}")
            # Close positions
            for d in self.datas[1:]:
                size = self.getposition(d).size
                if size != 0:
                    # self.log(f"{d.name},{size},{self.getposition(d).price},{d.open[1]}")
                    self.close(d)
            # self.trade_num += 1
            if True:
                sorted_result = sorted(result, key=lambda x: x[1])
                # Select some for short, select some for long
                num = int(len(sorted_result) * self.p.percent)
                long_list = sorted_result[-num:]
                short_list = sorted_result[:num]
                # self.log(f"result:{sorted_result}")
                # self.log(f"long_list: {long_list}")
                # self.log(f"short_list: {short_list}")
                # Loop through long list to place orders
                for key, _ in long_list:
                    total_value = 0.01 * self.broker.get_value()
                    contract_value = total_value / (num * 2)
                    data = self.getdatabyname(key)
                    info = self.broker.getcommissioninfo(data)
                    # margin = info.p.margin
                    mult = info.p.mult
                    close = data.close[0]
                    lots = contract_value / (close * mult)
                    if lots > 0:
                        self.buy(data, size=lots)
                # Loop through short list to place orders
                for key, _ in short_list:
                    total_value = 0.01 * self.broker.get_value()
                    contract_value = total_value / (num * 2)
                    data = self.getdatabyname(key)
                    info = self.broker.getcommissioninfo(data)
                    # margin = info.p.margin
                    mult = info.p.mult
                    close = data.close[0]
                    lots = contract_value / (close * mult)
                    if lots > 0:
                        self.sell(data, size=lots)
        # Increment bar count by 1
        self.bar_num = self.bar_num + 1

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Rejected:
            self.log(f"Rejected : order_ref:{order.ref}  data_name:{order.p.data.name}")

        if order.status == order.Margin:
            self.log(f"Margin : order_ref:{order.ref}  data_name:{order.p.data.name}")

        if order.status == order.Cancelled:
            self.log(f"Cancelled : order_ref:{order.ref}  data_name:{order.p.data.name}")

        if order.status == order.Partial:
            self.log(f"Partial : order_ref:{order.ref}  data_name:{order.p.data.name}")

        if order.status == order.Completed:
            if order.isbuy():
                self.log(
                    f" BUY : data_name:{order.p.data.name} price : {order.executed.price} "
                    f" cost : {order.executed.value} , commission : {order.executed.comm}"
                )

            else:  # Sell
                self.log(
                    f" SELL : data_name:{order.p.data.name} price : {order.executed.price} "
                    f" cost : {order.executed.value} , commission : {order.executed.comm}"
                )

    #
    def notify_trade(self, trade):
        # Output information when a trade ends
        if trade.isclosed:
            self.log(
                f"closed symbol: {trade.getdataname()} ,total_profit: {trade.pnl} ,net_profit: {trade.pnlcomm}"
            )

        if trade.isopen:
            self.log(f"open symbol is: {trade.getdataname()} , price: {trade.price} ")

    def stop(self):
        pass
        # signal_df = pd.DataFrame(self.signals)
        # signal_df.to_csv("d:/result/backtrader_signal.csv")
        # # for key in self.returns:
        # #     print(key, len(self.returns[key]))
        # returns_df = pd.DataFrame(self.returns)
        # returns_df.to_csv("d:/result/backtrader_returns.csv")


def run(n_rows=10000, n_data=1000):
    # print(params)
    new_params = {"look_back_days": 200, "hold_days": 200, "percent": 0.2}
    cerebro = bt.Cerebro()
    for i in range(n_data):
        np.random.seed(i)
        data = pd.DataFrame(
            {
                i: np.random.randn(n_rows)
                for i in ["open", "high", "low", "close", "volume", "total_value"]
            }
        )
        data.index = pd.date_range("1/1/2012", periods=len(data), freq="5min")
        feed = bt.feeds.PandasDirectData(dataname=data)
        # Add contract data
        cerebro.adddata(feed, name=f"data_{i}")

        comm_params = {"commission": 0.0002, "margin": 0.1, "mult": 10}
        comm = ComminfoFuturesPercent(**comm_params)
        cerebro.broker.addcommissioninfo(comm, name=f"data_{i}")
    # Configure slippage cost, 1 tick
    # cerebro.broker.set_slippage_fixed(slippage*1)
    cerebro.broker.setcash(100000000.0)
    # Add strategy
    cerebro.addstrategy(CloseMaCs, **new_params)
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    # Add AnnualReturn
    cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name="my_annual_return")
    # Calmar
    cerebro.addanalyzer(bt.analyzers.Calmar, _name="my_calmar", timeframe=bt.TimeFrame.NoTimeFrame)
    # DrawDown
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    # TimeDrawDown
    cerebro.addanalyzer(bt.analyzers.TimeDrawDown, _name="my_time_drawdown")
    # GrossLeverage
    cerebro.addanalyzer(bt.analyzers.GrossLeverage, _name="my_gross_leverage")
    # PositionsValue
    cerebro.addanalyzer(bt.analyzers.PositionsValue, _name="my_positions_value")
    # LogReturnsRolling
    cerebro.addanalyzer(bt.analyzers.LogReturnsRolling, _name="my_log_returns_rolling")
    # PeriodStats
    cerebro.addanalyzer(bt.analyzers.PeriodStats, _name="my_period_stats")
    # Returns
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    # SharpeRatio
    cerebro.addanalyzer(
        bt.analyzers.SharpeRatio,
        _name="my_sharpe",
        timeframe=bt.TimeFrame.Days,
        riskfreerate=0.00,
        annualize=True,
        factor=250,
    )
    # SharpeRatio_A
    cerebro.addanalyzer(bt.analyzers.SharpeRatioA, _name="my_sharpe_ratio_a")
    # SQN
    cerebro.addanalyzer(bt.analyzers.SQN, _name="my_sqn")
    # TimeReturn
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="my_time_return")
    # TradeAnalyzer
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")
    # Transactions
    cerebro.addanalyzer(bt.analyzers.Transactions, _name="my_transactions")
    # VWR
    # cerebro.addanalyzer(bt.analyzers.VWR, _name='my_vwr')
    # Analyze analyzer results
    # cerebro.addanalyzer(bt.analyzers.PyFolio)
    # Run backtest
    my_results = cerebro.run()
    # sharpe_ratio = my_results[0].analyzers.my_sharpe.get_analysis()["sharperatio"]
    # annual_return = my_results[0].analyzers.my_returns.get_analysis()["rnorm"]
    # max_drawdown = my_results[0].analyzers.my_drawdown.get_analysis()["max"]["drawdown"] / 100
    trade_num = (
        my_results[0].analyzers.my_trade_analyzer.get_analysis().get("total", {}).get("total", 0)
    )
    won_num = (
        my_results[0].analyzers.my_trade_analyzer.get_analysis().get("won", {}).get("total", 0)
    )
    if trade_num == 0:
        _profit_percent = 0
    else:
        _profit_percent = round(won_num / trade_num, 3)

    value_df = pd.DataFrame([my_results[0].analyzers.my_value.get_analysis()]).T
    value_df.columns = ["value"]
    value_df["datetime"] = pd.to_datetime(value_df.index)
    value_df["date"] = [i.date() for i in value_df["datetime"]]
    value_df = value_df.drop_duplicates("date", keep="last")
    value_df = value_df[["value"]]
    return value_df


if __name__ == "__main__":
    begin_time = time.perf_counter()
    total_value = run(n_rows=10000, n_data=100)
    end_time = time.perf_counter()
    print(f"Time elapsed: {end_time - begin_time}")
    print("Results:", total_value.tail())
