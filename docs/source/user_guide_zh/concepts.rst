========
核心概念
========

理解 Lines（数据线）
--------------------

**Lines** 是 Backtrader 的基础数据结构。它们代表时间序列数据，
每个点对应一个特定的时间（K线）。

.. code-block:: python

   # 访问当前K线的值
   current_close = self.data.close[0]
   
   # 访问前一根K线的值
   previous_close = self.data.close[-1]
   
   # 访问5根K线前的值
   close_5_bars_ago = self.data.close[-5]

.. note::
   索引 ``[0]`` 是当前K线，负数索引向历史回溯。

数据源
------

数据源提供 OHLCV 数据：

- **Open**: 开盘价
- **High**: 最高价
- **Low**: 最低价
- **Close**: 收盘价
- **Volume**: 成交量
- **OpenInterest**: 持仓量（期货）

.. code-block:: python

   # 访问数据线
   self.data.open[0]
   self.data.high[0]
   self.data.low[0]
   self.data.close[0]
   self.data.volume[0]
   self.data.datetime[0]  # 浮点数表示

时间周期
--------

支持的时间周期：

- ``TimeFrame.Ticks`` - Tick
- ``TimeFrame.Seconds`` - 秒
- ``TimeFrame.Minutes`` - 分钟
- ``TimeFrame.Days`` - 日
- ``TimeFrame.Weeks`` - 周
- ``TimeFrame.Months`` - 月
- ``TimeFrame.Years`` - 年

指标
----

指标从数据中计算值：

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def __init__(self):
           # 指标自动为每根K线计算
           self.sma = bt.indicators.SMA(self.data.close, period=20)
       
       def next(self):
           # 使用指标值
           if self.data.close[0] > self.sma[0]:
               self.buy()

订单
----

订单类型：

- **Market（市价单）**: 以当前价格执行
- **Limit（限价单）**: 以指定价格或更优价格执行
- **Stop（止损单）**: 当价格达到触发价时执行
- **StopLimit（止损限价单）**: 止损和限价的组合

.. code-block:: python

   # 市价单
   self.buy()
   
   # 限价单
   self.buy(exectype=bt.Order.Limit, price=100.0)
   
   # 止损单
   self.buy(exectype=bt.Order.Stop, price=105.0)
   
   # 止损限价单
   self.buy(exectype=bt.Order.StopLimit, price=105.0, plimit=106.0)

持仓
----

持仓代表某个资产的持有情况：

.. code-block:: python

   # 检查是否有持仓
   if self.position:
       print(f'数量: {self.position.size}')
       print(f'价格: {self.position.price}')
   
   # 检查特定数据的持仓
   pos = self.getposition(self.data)

事件驱动模型
------------

Backtrader 使用事件驱动模型：

1. ``start()``: 开始时调用
2. ``prenext()``: 最小周期之前调用
3. ``nextstart()``: 达到最小周期时调用一次
4. ``next()``: 之后每根K线调用
5. ``stop()``: 结束时调用

通知事件：

- ``notify_order(order)``: 订单状态变化
- ``notify_trade(trade)``: 交易更新
- ``notify_cashvalue(cash, value)``: 资金更新
