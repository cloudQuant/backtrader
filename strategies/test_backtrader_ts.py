"""用于测试backtrader在时间序列上运行的效率"""
import pandas as pd
import numpy as np
import backtrader as bt
import datetime
import time

class SmaStrategy(bt.Strategy):
    # params = (('short_window',10),('long_window',60))
    params = {"short_window": 10, "long_window": 60}

    def log(self, txt, dt=None):
        ''' log信息的功能'''
        dt = dt or self.datas[0].datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        # 一般用于计算指标或者预先加载数据，定义变量使用
        self.short_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.short_window)
        self.long_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.long_window)

    def next(self):
        # Simply log the closing price of the series from the reference
        # self.log(f"工商银行,{self.datas[0].datetime.date(0)},收盘价为：{self.datas[0].close[0]}")
        # self.log(f"short_ma:{self.short_ma[0]},long_ma:{self.long_ma[0]}")
        # 得到当前的size
        size = self.getposition(self.datas[0]).size
        # 做多
        if size == 0 and self.short_ma[-1] < self.long_ma[-1] and self.short_ma[0] > self.long_ma[0]:
            # 开仓
            self.buy(self.datas[0],size=1000)
        # 平多
        if size > 0 and self.short_ma[-1] > self.long_ma[-1] and self.short_ma[0] < self.long_ma[0]:
            self.close(self.datas[0])

    # def notify_order(self, order):
    #     if order.status in [order.Submitted, order.Accepted]:
    #         # order被提交和接受
    #         return
    #     if order.status == order.Rejected:
    #         self.log(f"order is rejected : order_ref:{order.ref}  order_info:{order.info}")
    #     if order.status == order.Margin:
    #         self.log(f"order need more margin : order_ref:{order.ref}  order_info:{order.info}")
    #     if order.status == order.Cancelled:
    #         self.log(f"order is concelled : order_ref:{order.ref}  order_info:{order.info}")
    #     if order.status == order.Partial:
    #         self.log(f"order is partial : order_ref:{order.ref}  order_info:{order.info}")
    #     # Check if an order has been completed
    #     # Attention: broker could reject order if not enougth cash
    #     if order.status == order.Completed:
    #         if order.isbuy():
    #             self.log("buy result : buy_price : {} , buy_cost : {} , commission : {}".format(
    #                 order.executed.price, order.executed.value, order.executed.comm))
    #
    #         else:  # Sell
    #             self.log("sell result : sell_price : {} , sell_cost : {} , commission : {}".format(
    #                 order.executed.price, order.executed.value, order.executed.comm))
    #
    #
    # def notify_trade(self, trade):
    #     # 一个trade结束的时候输出信息
    #     if trade.isclosed:
    #         self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
    #             trade.getdataname(), trade.pnl, trade.pnlcomm))
    #         # self.trade_list.append([self.datas[0].datetime.date(0),trade.getdataname(),trade.pnl,trade.pnlcomm])
    #
    #     if trade.isopen:
    #         self.log('open symbol is : {} , price : {} '.format(
    #             trade.getdataname(), trade.price))
    #
    # def stop(self):
    #     # 策略停止的时候输出信息
    #     pass


def run_strategy(n_rows=100000):
    # 添加cerebro
    cerebro = bt.Cerebro()
    # 添加策略
    cerebro.addstrategy(SmaStrategy)
    cerebro.broker.setcash(5000000.0)
    # 准备数据
    # 使用numpy生成n_rows行数据
    np.random.seed(1)
    data = pd.DataFrame({i: np.random.randn(n_rows) for i in ['open', 'high', 'low', 'close', 'volume', "total_value"]})
    data.index = pd.date_range('1/1/2012', periods=len(data), freq='5min')
    feed = bt.feeds.PandasDirectData(dataname=data)
    # 添加合约数据
    cerebro.adddata(feed, name="test")
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name='_TotalValue')
    cerebro.addanalyzer(bt.analyzers.PyFolio)
    # 运行回测
    results = cerebro.run()

    pyfoliozer = results[0].analyzers.getbyname('pyfolio')
    total_value = results[0].analyzers.getbyname('_TotalValue').get_analysis()
    total_value = pd.DataFrame([total_value]).T
    returns, positions, transactions, gross_lev = pyfoliozer.get_pf_items()
    # print(total_value)
    return total_value

if __name__ == "__main__":
    begin_time = time.perf_counter()
    total_value = run_strategy(n_rows=100000)
    end_time = time.perf_counter()
    print(f"运行耗费的时间为:{end_time - begin_time}")
    print("运行结果为:",total_value.tail())