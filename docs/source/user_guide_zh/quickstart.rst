========
快速入门
========

本指南将帮助你创建第一个回测。

基本结构
--------

一个典型的回测包括：

1. 创建 Cerebro 引擎
2. 添加数据
3. 添加策略
4. 配置经纪商
5. 运行回测
6. 分析结果

你的第一个回测
--------------

.. code-block:: python

   import backtrader as bt
   import datetime
   
   # 创建一个简单的策略
   class SmaCross(bt.Strategy):
       params = (('pfast', 10), ('pslow', 30),)
       
       def __init__(self):
           sma1 = bt.ind.SMA(period=self.p.pfast)
           sma2 = bt.ind.SMA(period=self.p.pslow)
           self.crossover = bt.ind.CrossOver(sma1, sma2)
       
       def next(self):
           if not self.position:
               if self.crossover > 0:
                   self.buy()
           elif self.crossover < 0:
               self.close()
   
   # 创建 cerebro
   cerebro = bt.Cerebro()
   
   # 添加数据
   data = bt.feeds.YahooFinanceCSVData(
       dataname='AAPL.csv',
       fromdate=datetime.datetime(2020, 1, 1),
       todate=datetime.datetime(2021, 1, 1)
   )
   cerebro.adddata(data)
   
   # 添加策略
   cerebro.addstrategy(SmaCross)
   
   # 设置初始资金
   cerebro.broker.setcash(100000)
   
   # 添加分析器
   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
   
   # 运行
   print(f'初始资金: {cerebro.broker.getvalue():.2f}')
   results = cerebro.run()
   print(f'最终资金: {cerebro.broker.getvalue():.2f}')
   
   # 获取分析结果
   strat = results[0]
   print(f'夏普比率: {strat.analyzers.sharpe.get_analysis()}')
   
   # 绑制图表
   cerebro.plot()

理解输出
--------

运行后：

- **资金价值**: 显示盈亏
- **夏普比率**: 风险调整后的收益指标
- **图表**: 交易的可视化展示

下一步
------

- :doc:`concepts` - 学习核心概念
- :doc:`strategies` - 构建复杂策略
- :doc:`indicators` - 使用技术指标
- :doc:`analyzers` - 分析性能
