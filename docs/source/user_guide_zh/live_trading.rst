==========
实盘交易
==========

Backtrader 通过与各种经纪商和交易所的集成来支持实盘交易。
本指南介绍从回测过渡到实盘交易的设置和最佳实践。

支持的经纪商
------------

.. list-table::
   :widths: 25 25 50
   :header-rows: 1

   * - 经纪商
     - 市场
     - 描述
   * - 盈透证券 (IB)
     - 股票、期货、期权、外汇
     - 专业多资产经纪商
   * - CCXT
     - 加密货币
     - 100+ 加密货币交易所
   * - Alpaca
     - 美股
     - 零佣金交易
   * - OANDA
     - 外汇
     - 外汇交易平台

盈透证券集成
------------

前置条件
^^^^^^^^

1. 安装 IB Gateway 或 TWS（交易工作站）
2. 在 IB 设置中启用 API 连接
3. 安装 ``ib_insync`` 包

.. code-block:: bash

   pip install ib_insync

配置
^^^^

.. code-block:: python

   import backtrader as bt
   from backtrader.stores import IBStore
   
   # 创建 IB store
   ibstore = IBStore(
       host='127.0.0.1',
       port=7497,           # 7497 用于 TWS 模拟盘，7496 用于实盘
       clientId=1,
       notifyall=False,
       _debug=False
   )
   
   cerebro = bt.Cerebro()
   
   # 设置 IB 作为经纪商
   cerebro.setbroker(ibstore.getbroker())

实时数据源
^^^^^^^^^^

.. code-block:: python

   from backtrader.feeds import IBData
   
   # 股票数据
   data = IBData(
       dataname='AAPL',
       sectype='STK',
       exchange='SMART',
       currency='USD',
       historical=True,
       what='TRADES',
       useRTH=True,
       qcheck=0.5,
       backfill_start=True,
       backfill=True,
       latethrough=False
   )
   
   cerebro.adddata(data)

期货数据
^^^^^^^^

.. code-block:: python

   # E-mini S&P 500 期货
   data = IBData(
       dataname='ES',
       sectype='FUT',
       exchange='CME',
       currency='USD',
       expiry='202403'
   )

实盘策略示例
^^^^^^^^^^^^

.. code-block:: python

   class IBLiveStrategy(bt.Strategy):
       params = (('period', 20),)
       
       def __init__(self):
           self.sma = bt.indicators.SMA(period=self.params.period)
           self.order = None
       
       def log(self, txt, dt=None):
           dt = dt or self.data.datetime.datetime(0)
           print(f'{dt.isoformat()} {txt}')
       
       def notify_order(self, order):
           if order.status in [order.Submitted, order.Accepted]:
               return
           
           if order.status == order.Completed:
               if order.isbuy():
                   self.log(f'买入成交 @ {order.executed.price:.2f}')
               else:
                   self.log(f'卖出成交 @ {order.executed.price:.2f}')
           
           self.order = None
       
       def next(self):
           if self.order:
               return
           
           if not self.position:
               if self.data.close[0] > self.sma[0]:
                   self.order = self.buy()
           else:
               if self.data.close[0] < self.sma[0]:
                   self.order = self.close()

CCXT 加密货币集成
-----------------

安装
^^^^

.. code-block:: bash

   pip install ccxt

配置
^^^^

.. code-block:: python

   import backtrader as bt
   from backtrader.stores import CCXTStore
   
   # 创建币安的 CCXT store
   config = {
       'apiKey': 'your_api_key',
       'secret': 'your_secret',
       'enableRateLimit': True,
   }
   
   store = CCXTStore(
       exchange='binance',
       currency='USDT',
       config=config,
       retries=5,
       sandbox=True  # 使用沙盒测试
   )
   
   cerebro = bt.Cerebro()
   cerebro.setbroker(store.getbroker())

加密货币数据源
^^^^^^^^^^^^^^

.. code-block:: python

   from backtrader.feeds import CCXTFeed
   
   # BTC/USDT 1小时K线
   data = CCXTFeed(
       exchange='binance',
       symbol='BTC/USDT',
       timeframe=bt.TimeFrame.Minutes,
       compression=60,
       config=config,
       retries=5,
       historical=True,
       backfill=True
   )
   
   cerebro.adddata(data)

多周期数据与重采样
------------------

使用实时数据进行多周期分析时：

.. code-block:: python

   # 基础数据（1分钟）
   data0 = IBData(
       dataname='AAPL',
       sectype='STK',
       exchange='SMART',
       currency='USD',
       timeframe=bt.TimeFrame.Minutes,
       compression=1
   )
   cerebro.adddata(data0)
   
   # 重采样为5分钟
   cerebro.resampledata(
       data0,
       timeframe=bt.TimeFrame.Minutes,
       compression=5
   )
   
   # 重采样为1小时
   cerebro.resampledata(
       data0,
       timeframe=bt.TimeFrame.Minutes,
       compression=60
   )

.. warning::
   在实盘交易中使用重采样数据时，请注意时间问题。
   重采样的K线只有在基础周期的下一根K线到达时才算完成。

模拟盘交易
----------

在进行实盘交易之前，务必先用模拟盘测试策略：

盈透证券模拟盘
^^^^^^^^^^^^^^

.. code-block:: python

   # 使用模拟盘端口
   ibstore = IBStore(
       host='127.0.0.1',
       port=7497,  # 模拟盘端口
       clientId=1
   )

CCXT 沙盒
^^^^^^^^^

.. code-block:: python

   store = CCXTStore(
       exchange='binance',
       currency='USDT',
       config=config,
       sandbox=True  # 启用沙盒模式
   )

实盘交易风险管理
----------------

仓位限制
^^^^^^^^

.. code-block:: python

   class SafeStrategy(bt.Strategy):
       params = (
           ('max_position_pct', 0.1),  # 每笔最多 10%
           ('max_daily_trades', 10),
       )
       
       def __init__(self):
           self.daily_trades = 0
           self.last_trade_date = None
       
       def next(self):
           # 重置每日计数器
           current_date = self.data.datetime.date(0)
           if current_date != self.last_trade_date:
               self.daily_trades = 0
               self.last_trade_date = current_date
           
           # 检查限制
           if self.daily_trades >= self.p.max_daily_trades:
               return
           
           # 计算仓位大小
           max_value = self.broker.getvalue() * self.p.max_position_pct
           size = int(max_value / self.data.close[0])
           
           if size > 0 and not self.position:
               self.buy(size=size)
               self.daily_trades += 1

紧急止损
^^^^^^^^

.. code-block:: python

   class EmergencyStopStrategy(bt.Strategy):
       params = (('max_drawdown_pct', 0.05),)  # 最大回撤 5%
       
       def __init__(self):
           self.initial_value = None
           self.emergency_stop = False
       
       def start(self):
           self.initial_value = self.broker.getvalue()
       
       def next(self):
           if self.emergency_stop:
               return
           
           # 检查回撤
           current_value = self.broker.getvalue()
           drawdown = (self.initial_value - current_value) / self.initial_value
           
           if drawdown >= self.p.max_drawdown_pct:
               self.log('紧急止损 - 达到最大回撤')
               self.close()  # 平仓所有头寸
               self.emergency_stop = True

日志和监控
----------

.. code-block:: python

   import logging
   
   # 设置日志
   logging.basicConfig(
       level=logging.INFO,
       format='%(asctime)s - %(levelname)s - %(message)s',
       handlers=[
           logging.FileHandler('trading.log'),
           logging.StreamHandler()
       ]
   )
   
   class LoggedStrategy(bt.Strategy):
       def log(self, txt, level=logging.INFO):
           dt = self.data.datetime.datetime(0)
           logging.log(level, f'{dt} - {txt}')
       
       def notify_order(self, order):
           if order.status == order.Completed:
               self.log(f'订单完成: {order.executed.price}')
           elif order.status in [order.Canceled, order.Rejected]:
               self.log(f'订单失败: {order.status}', logging.WARNING)

最佳实践
--------

1. **从模拟盘开始**：务必先在模拟盘/沙盒测试
2. **实现日志记录**：记录所有订单和交易以便复盘
3. **设置仓位限制**：永远不要冒超过承受能力的风险
4. **处理断线**：实现重连逻辑
5. **监控滑点**：比较预期和实际成交价格
6. **使用止损**：始终设置退出条件
7. **在交易时段测试**：在实际交易时段进行模拟盘测试

常见问题
--------

连接问题
^^^^^^^^

.. code-block:: python

   # 重连处理
   def notify_store(self, msg, *args, **kwargs):
       if 'connection' in msg.lower():
           self.log(f'Store 通知: {msg}')
           # 实现重连逻辑

数据缺口
^^^^^^^^

.. code-block:: python

   def next(self):
       # 检查数据缺口
       if len(self) > 1:
           time_diff = self.data.datetime[0] - self.data.datetime[-1]
           if time_diff > expected_interval * 2:
               self.log('警告: 检测到数据缺口')

参见
----

- :doc:`brokers` - 经纪商配置
- :doc:`strategies` - 策略开发
- :doc:`performance` - 性能优化
