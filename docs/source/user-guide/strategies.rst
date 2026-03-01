====
策略
====

策略包含你的交易逻辑。它们接收市场数据，计算指标，并生成交易信号。

策略生命周期
------------

理解策略生命周期（类似人生阶段）：

.. list-table::
   :widths: 20 20 60
   :header-rows: 1

   * - 方法
     - 阶段
     - 描述
   * - ``__init__``
     - 出生
     - 初始化指标和变量。开始时调用一次。
   * - ``start``
     - 准备
     - 处理开始前调用一次。通常为空。
   * - ``prenext``
     - 童年
     - 当最小周期未满足时调用（指标预热中）。
   * - ``nextstart``
     - 成年开始
     - 从 prenext 过渡到 next 时调用一次。
   * - ``next``
     - 成年
     - 主要交易逻辑。最小周期满足后每根 bar 调用。
   * - ``stop``
     - 结束
     - 所有数据处理完毕后调用一次。适合最终报告。

.. warning::
   当 **多个数据源** 的开始日期不同时，``next`` 不会被调用，直到所有数据源
   都有有效的 bar。如果需要，可以在 ``prenext`` 中手动调用 ``self.next()``，
   但要过滤掉尚未开始的数据。

策略结构
--------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       params = (
           ('period', 20),
           ('stake', 10),
       )
       
       def __init__(self):
           # 初始化指标（向量化计算）
           self.sma = bt.indicators.SMA(period=self.p.period)
           self.order = None
       
       def notify_order(self, order):
           # 处理订单通知
           if order.status in [order.Completed]:
               if order.isbuy():
                   self.log(f'买入 @ {order.executed.price:.2f}')
               else:
                   self.log(f'卖出 @ {order.executed.price:.2f}')
           self.order = None
       
       def next(self):
           # 交易逻辑 - 每根 bar 调用
           if self.order:
               return
           
           if not self.position:
               if self.data.close[0] > self.sma[0]:
                   self.order = self.buy(size=self.p.stake)
           else:
               if self.data.close[0] < self.sma[0]:
                   self.order = self.sell(size=self.p.stake)
       
       def log(self, txt):
           dt = self.datas[0].datetime.date(0)
           print(f'{dt} {txt}')

参数
----

定义和使用参数：

.. code-block:: python

   class MyStrategy(bt.Strategy):
       params = (
           ('fast', 10),
           ('slow', 30),
           ('risk', 0.02),
       )
       
       def __init__(self):
           # 访问参数
           print(f'快线: {self.p.fast}')
           print(f'慢线: {self.params.slow}')
   
   # 添加时覆盖参数
   cerebro.addstrategy(MyStrategy, fast=5, slow=20)

订单管理
--------

.. code-block:: python

   def next(self):
       # 简单买卖
       self.buy()
       self.sell()
       
       # 指定数量
       self.buy(size=100)
       
       # 限价单
       self.buy(exectype=bt.Order.Limit, price=99.0, size=100)
       
       # 止损单
       self.sell(exectype=bt.Order.Stop, price=95.0)
       
       # 括号订单（入场 + 止损 + 目标）
       self.buy_bracket(
           size=100,
           price=100.0,
           stopprice=95.0,
           limitprice=110.0
       )
       
       # 平仓
       self.close()
       
       # 撤单
       self.cancel(self.order)

多数据源
--------

.. code-block:: python

   class MultiDataStrategy(bt.Strategy):
       def __init__(self):
           # 为每个数据创建指标
           self.sma0 = bt.indicators.SMA(self.data0.close)
           self.sma1 = bt.indicators.SMA(self.data1.close)
       
       def next(self):
           # 交易不同品种
           if self.data0.close[0] > self.sma0[0]:
               self.buy(data=self.data0)
           
           if self.data1.close[0] < self.sma1[0]:
               self.sell(data=self.data1)

仓位管理
--------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def next(self):
           # 根据风险计算仓位
           risk_per_trade = self.broker.getvalue() * 0.02
           atr = self.atr[0]
           size = int(risk_per_trade / atr)
           
           self.buy(size=size)

日志和调试
----------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def log(self, txt, dt=None):
           dt = dt or self.datas[0].datetime.date(0)
           print(f'{dt.isoformat()} {txt}')
       
       def next(self):
           self.log(f'收盘价: {self.data.close[0]:.2f}')
           self.log(f'持仓: {self.position.size}')
           self.log(f'现金: {self.broker.getcash():.2f}')

多数据的 prenext 处理
-----------------------

当数据源的开始日期不同时：

.. code-block:: python

   class MultiDataStrategy(bt.Strategy):
       def prenext(self):
           # 在预热期间强制进入 next
           self.next()
       
       def next(self):
           for data in self.datas:
               # 检查此数据是否已开始
               if len(data) == 0:
                   continue
               
               # 检查数据是否为当前日期（而非历史）
               if data.datetime.date(0) != self.data.datetime.date(0):
                   continue
               
               # 现在可以安全使用此数据
               self.process_data(data)

通知方法
--------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def notify_order(self, order):
           '''订单状态变化时调用'''
           if order.status == order.Completed:
               print(f'订单 {order.ref} 已成交，价格 {order.executed.price}')
           elif order.status == order.Canceled:
               print(f'订单 {order.ref} 已取消')
           elif order.status == order.Rejected:
               print(f'订单 {order.ref} 已拒绝')
       
       def notify_trade(self, trade):
           '''交易状态变化时调用'''
           if trade.isclosed:
               print(f'交易盈亏: 毛利={trade.pnl:.2f}, 净利={trade.pnlcomm:.2f}')
       
       def notify_cashvalue(self, cash, value):
           '''现金/市值变化时调用'''
           print(f'现金: {cash:.2f}, 市值: {value:.2f}')

最佳实践
--------

1. **在 __init__ 中声明指标**: 启用向量化计算
2. **跟踪未完成订单**: 防止重复下单
3. **使用 notify_order**: 正确处理订单状态
4. **过滤多数据**: 在 prenext/next 中检查数据有效性
5. **记录关键事件**: 有助于调试和分析

参见
----

- :doc:`concepts` - 策略生命周期详情
- :doc:`indicators` - 使用指标
- :doc:`brokers` - 订单管理
- `博客: Strategy讲解 <https://yunjinqi.blog.csdn.net/article/details/108569865>`_
- `博客: prenext与next区别 <https://yunjinqi.blog.csdn.net/article/details/126337204>`_
