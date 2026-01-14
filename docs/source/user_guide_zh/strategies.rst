====
策略
====

策略结构
--------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       params = (
           ('period', 20),
           ('stake', 10),
       )
       
       def __init__(self):
           # 初始化指标
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
           # 交易逻辑
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
