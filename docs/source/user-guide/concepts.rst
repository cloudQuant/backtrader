========
核心概念
========

本章节讲解 Backtrader 的基本概念。理解这些概念是有效进行策略开发的基础。

.. tip::
   更详细的讲解请参见 `作者博客 <https://yunjinqi.blog.csdn.net/>`_。

理解 Lines（数据线）
--------------------

**Lines** 是 Backtrader 的基础数据结构，类似于 Excel 工作表中的列。
每个 Line 代表一个时间序列，每个点对应一个特定的时间（K线）。

可以这样理解：

- 一个 **类**（Strategy、Indicator）就像一个 **工作簿**
- 每个 **Line** 就像工作簿中的一 **列**
- 每根 **K线** 就像列中的一 **行**

.. code-block:: python

   # 访问当前K线的值（索引 0）
   current_close = self.data.close[0]
   
   # 访问前一根K线的值（索引 -1）
   previous_close = self.data.close[-1]
   
   # 访问5根K线前的值
   close_5_bars_ago = self.data.close[-5]
   
   # 获取多个值作为数组
   last_10_closes = self.data.close.get(size=10)

.. note::
   索引 ``[0]`` 是当前K线，负数索引向历史回溯。
   正数索引 ``[1]``、``[2]`` 向前查看（仅在指标的 ``__init__`` 中有效）。

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

策略生命周期
------------

Backtrader 使用事件驱动模型。作者将其比作人的生命周期：

.. list-table::
   :widths: 20 20 60
   :header-rows: 1

   * - 方法
     - 生命阶段
     - 描述
   * - ``__init__``
     - 怀孕
     - 初始化指标和变量
   * - ``start``
     - 出生
     - 开始时调用一次，通常为空
   * - ``prenext``
     - 童年
     - 在指标有足够数据之前调用
   * - ``nextstart``
     - 成年礼
     - 达到最小周期时调用一次
   * - ``next``
     - 成年
     - 主要交易逻辑，每根K线调用
   * - ``stop``
     - 死亡
     - 结束时调用，在此输出结果

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def __init__(self):
           '''初始化指标和变量'''
           self.sma = bt.indicators.SMA(period=20)
           self.order = None
       
       def start(self):
           '''开始时调用一次'''
           self.log('策略开始运行')
       
       def prenext(self):
           '''在指标有足够数据之前调用。
           用于调试或早期逻辑。'''
           pass
       
       def nextstart(self):
           '''达到最小周期时调用一次'''
           self.next()  # 通常直接调用 next()
       
       def next(self):
           '''主要交易逻辑 - 每根K线调用'''
           if self.data.close[0] > self.sma[0]:
               self.buy()
       
       def stop(self):
           '''结束时调用 - 输出结果'''
           self.log(f'最终资金: {self.broker.getvalue():.2f}')

通知事件
~~~~~~~~

.. code-block:: python

   def notify_order(self, order):
       '''订单状态变化时调用'''
       if order.status == order.Submitted:
           return  # 订单已提交给经纪商
       if order.status == order.Accepted:
           return  # 订单已被经纪商接受
       if order.status == order.Completed:
           if order.isbuy():
               self.log(f'买入成交 @ {order.executed.price:.2f}')
           else:
               self.log(f'卖出成交 @ {order.executed.price:.2f}')
       elif order.status == order.Canceled:
           self.log('订单已取消')
       elif order.status == order.Margin:
           self.log('保证金不足')
       elif order.status == order.Rejected:
           self.log('订单被拒绝')
   
   def notify_trade(self, trade):
       '''交易开仓或平仓时调用'''
       if trade.isclosed:
           self.log(f'交易平仓 - 盈亏: {trade.pnl:.2f}, 净盈亏: {trade.pnlcomm:.2f}')
       if trade.isopen:
           self.log(f'交易开仓 @ {trade.price:.2f}')

Cerebro - 大脑
--------------

Cerebro 是协调一切的中心引擎：

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # 1. 添加数据
   data = bt.feeds.GenericCSVData(dataname='data.csv')
   cerebro.adddata(data, name='AAPL')
   
   # 2. 添加策略和参数
   cerebro.addstrategy(MyStrategy, period=20, stake=100)
   
   # 3. 添加分析器
   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
   
   # 4. 添加观察者（用于绘图）
   cerebro.addobserver(bt.observers.Broker)
   cerebro.addobserver(bt.observers.Trades)
   cerebro.addobserver(bt.observers.BuySell)
   
   # 5. 设置经纪商参数
   cerebro.broker.setcash(100000)
   cerebro.broker.setcommission(commission=0.001)
   
   # 6. 运行
   results = cerebro.run()
   
   # 7. 获取结果
   strat = results[0]
   print(f"夏普比率: {strat.analyzers.sharpe.get_analysis()}")
   
   # 8. 绘图
   cerebro.plot()

Cerebro 关键参数
~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 20 15 65
   :header-rows: 1

   * - 参数
     - 默认值
     - 描述
   * - preload
     - True
     - 预加载数据到内存（回测更快）
   * - runonce
     - True
     - 向量化计算指标（更快）
   * - live
     - False
     - 实盘模式（禁用 preload 和 runonce）
   * - maxcpus
     - None
     - 优化时使用的CPU数（None = 全部）
   * - stdstats
     - True
     - 添加默认观察者（Broker, Trades, BuySell）

参见
----

- :doc:`strategies` - 策略开发
- :doc:`data_feeds` - 数据加载
- :doc:`indicators` - 技术指标
