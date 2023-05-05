"""用于测试backtrader和ts在时间序列上运行的效率,以及python,numba,cython改写具体函数后提高的效率"""
import pandas as pd
import numpy as np
import backtrader as bt
import datetime
import time
from backtrader.comminfo import ComminfoFuturesPercent,ComminfoFuturesFixed
from backtrader.vectors.ts import AlphaTs

class alphats001(AlphaTs):
    # params = (('short_window',10),('long_window',60))
    # def cal_signal(self):
    #     short_ma = np.convolve(self.close_arr, np.ones(self.params["short_window"]), 'valid') / self.params["short_window"]
    #     long_ma = np.convolve(self.close_arr, np.ones(self.params["long_window"]), 'valid') / self.params["long_window"]
    #     signal_arr = np.where(short_ma>=long_ma,1,0)
    #     return signal_arr
    pass
def run_ts_strategy(n_rows=1000,engine="python"):
    # 准备数据
    # 使用numpy生成n_rows行数据
    np.random.seed(1)
    data = pd.DataFrame({i: np.random.randn(n_rows) for i in ['open', 'high', 'low', 'close', 'volume', "total_value"]})
    data.index = pd.date_range('1/1/2012', periods=len(data), freq='5min')
    data = data+100
    # 设置参数
    params = {"short_window": 10, "long_window": 60, "commission":0.0002, "init_value":100000000,'percent':0.01}
    # 计算均线
    data['short_ma'] = data['close'].rolling(params['short_window']).mean()
    data['long_ma'] = data['close'].rolling(params['long_window']).mean()
    # 计算信号
    data['signal'] = np.where(data['short_ma']>=data['long_ma'],1,0)
#     print(data[data['signal']!=0])
#     data.to_csv("d:/test/test_ts.csv")
    strategy = alphats001(np.array(data.index),
                          np.array(data['open']),
                          np.array(data['high']),
                          np.array(data['low']),
                          np.array(data['close']),
                          np.array(data['volume']),
                          params,
                          signal_arr=np.array(data['signal']),
                         engine=engine)
    total_value = strategy.run()
    total_value.columns=['ts']
    # print(total_value)
    return total_value

class SmaStrategy(bt.Strategy):
    # params = (('short_window',10),('long_window',60))
    params = {"short_window": 10, "long_window": 60}

    def log(self, txt, dt=None):
        ''' log信息的功能'''
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        # 一般用于计算指标或者预先加载数据，定义变量使用
        self.short_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.short_window)
        self.long_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.long_window)

    def next(self):
        # Simply log the closing price of the series from the reference
        # self.log(f"工商银行,{self.datas[0].datetime.date(0)},收盘价为：{self.datas[0].close[0]}")
        # 得到当前的size
        size = self.getposition(self.datas[0]).size
        value = self.broker.get_value()
#         self.log(f"short_ma:{self.short_ma[0]},long_ma:{self.long_ma[0]},size={size},当前bar收盘之后的账户价值为:{value}")
        # 做多
        if size == 0 and  self.short_ma[0] > self.long_ma[0]:
            # 开仓,计算一倍杠杆下可以交易的手数
            info = self.broker.getcommissioninfo(self.datas[0])
            symbol_multi = info.p.mult
            try:
                # 引用下一根bar的开盘价计算具体的手数
                lots = 0.01*value/(self.datas[0].open[1]*symbol_multi)
            except:
                lots = 0.01*value /(self.datas[0].close[0]*symbol_multi)
            self.buy(self.datas[0],size=lots)
        # 平多
        if size > 0 and  self.short_ma[0] < self.long_ma[0]:
            self.close(self.datas[0])

#     def notify_order(self, order):
#         if order.status in [order.Submitted, order.Accepted]:
#             # order被提交和接受
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
#                     order.executed.price, order.executed.value, order.executed.comm))

#             else:  # Sell
#                 self.log("sell result : sell_price : {} , sell_cost : {} , commission : {}".format(
#                     order.executed.price, order.executed.value, order.executed.comm))


#     def notify_trade(self, trade):
#         # 一个trade结束的时候输出信息
#         if trade.isclosed:
#             self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
#                 trade.getdataname(), trade.pnl, trade.pnlcomm))
#             # self.trade_list.append([self.datas[0].datetime.date(0),trade.getdataname(),trade.pnl,trade.pnlcomm])

#         if trade.isopen:
#             self.log('open symbol is : {} , price : {} '.format(
#                 trade.getdataname(), trade.price))
    #
    # def stop(self):
    #     # 策略停止的时候输出信息
    #     pass


def run_backtrader_strategy(n_rows=1000):
    # 添加cerebro
    cerebro = bt.Cerebro()
    # 添加策略
    cerebro.addstrategy(SmaStrategy)
    cerebro.broker.setcash(100000000.0)

    # 准备数据
    # 使用numpy生成n_rows行数据,为了尽可能避免出现负数，把data+3
    np.random.seed(1)
    data = pd.DataFrame({i: np.random.randn(n_rows) for i in ['open', 'high', 'low', 'close', 'volume', "total_value"]})
    data.index = pd.date_range('1/1/2012', periods=len(data), freq='5min')
    data = data+100
    feed = bt.feeds.PandasDirectData(dataname=data)
    # 添加合约数据
    cerebro.adddata(feed, name="test")
    # 设置合约属性
    comm = ComminfoFuturesPercent(commission=0.0002, margin=1, mult=1)
    cerebro.broker.addcommissioninfo(comm, name="test")
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name='_TotalValue')
    cerebro.addanalyzer(bt.analyzers.PyFolio)
    # 运行回测
    results = cerebro.run()
    # cerebro.plot()
    pyfoliozer = results[0].analyzers.getbyname('pyfolio')
    total_value = results[0].analyzers.getbyname('_TotalValue').get_analysis()
    total_value = pd.DataFrame([total_value]).T
    returns, positions, transactions, gross_lev = pyfoliozer.get_pf_items()
    # print(total_value)
    total_value.columns=['backtrader']
    return total_value

n_rows = 1000000
begin_time = time.perf_counter()
backtrader_total_value = run_backtrader_strategy(n_rows=n_rows)
end_time = time.perf_counter()
print(f"backtrader运行耗费的时间为:{end_time - begin_time}")

begin_time = time.perf_counter()
ts_python_total_value = run_ts_strategy(n_rows=n_rows,engine="python")
end_time = time.perf_counter()
ts_python_total_value.columns=["ts_python"]
print(f"ts_python运行耗费的时间为:{end_time - begin_time}")


begin_time = time.perf_counter()
ts_numba_total_value = run_ts_strategy(n_rows=n_rows,engine="numba")
end_time = time.perf_counter()
ts_numba_total_value.columns=["ts_numba"]
print(f"ts_numba运行耗费的时间为:{end_time - begin_time}")

begin_time = time.perf_counter()
ts_cython_total_value = run_ts_strategy(n_rows=n_rows,engine="cython")
end_time = time.perf_counter()
ts_cython_total_value.columns=["ts_cython"]
print(f"ts_cython运行耗费的时间为:{end_time - begin_time}")

df = pd.concat([backtrader_total_value,ts_numba_total_value,ts_python_total_value,ts_cython_total_value],join="outer",axis=1)
# df = pd.concat([ts_numba_total_value,ts_python_total_value,ts_cython_total_value],join="outer",axis=1)
print(df.corr())
"""
backtrader运行耗费的时间为:218.7071305999998
ts_python运行耗费的时间为:1.6099043001886457
ts_numba运行耗费的时间为:0.35054199979640543
ts_cython运行耗费的时间为:0.351795099908486
            backtrader  ts_numba  ts_python  ts_cython
backtrader    1.000000  0.999998   0.999998   0.999998
ts_numba      0.999998  1.000000   1.000000   1.000000
ts_python     0.999998  1.000000   1.000000   1.000000
ts_cython     0.999998  1.000000   1.000000   1.000000
"""
# df.plot()