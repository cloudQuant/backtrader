.. Backtrader 文档主页

=======================================
Backtrader 文档
=======================================

|github| |gitee| |python| |license|

.. |github| image:: https://img.shields.io/badge/GitHub-cloudQuant%2Fbacktrader-blue?logo=github
   :target: https://github.com/cloudQuant/backtrader
   :alt: GitHub

.. |gitee| image:: https://img.shields.io/badge/Gitee-yunjinqi%2Fbacktrader-red?logo=gitee
   :target: https://gitee.com/yunjinqi/backtrader
   :alt: Gitee

.. |python| image:: https://img.shields.io/badge/Python-3.9+-green?logo=python
   :alt: Python

.. |license| image:: https://img.shields.io/badge/License-GPLv3-orange
   :alt: License

**Backtrader** 是一个功能丰富的Python量化交易框架，支持回测和实盘交易，
提供50+技术指标、20+数据源、多种经纪商和全面的分析工具。

.. note::
   本文档提供中文和 `English (英文) <index.html>`_ 两种语言版本。
   
   作者博客： `https://yunjinqi.blog.csdn.net/ <https://yunjinqi.blog.csdn.net/>`_

为什么选择 Backtrader？
-----------------------

- **易于学习**：学习曲线平缓，API设计直观
- **高性能**：支持向量化(runonce)和事件驱动(runnext)两种模式
- **组件丰富**：50+指标、17+分析器、21+数据源
- **专业可视化**：支持Plotly、Bokeh、Matplotlib
- **实盘就绪**：支持盈透证券(IB)、CCXT等
- **全面报告**：一键生成HTML/PDF/JSON格式报告

快速开始
--------

.. code-block:: python

   import backtrader as bt

   class SmaCrossStrategy(bt.Strategy):
       params = (('快线周期', 10), ('慢线周期', 30))
       
       def __init__(self):
           fast_sma = bt.indicators.SMA(period=self.params.快线周期)
           slow_sma = bt.indicators.SMA(period=self.params.慢线周期)
           self.crossover = bt.indicators.CrossOver(fast_sma, slow_sma)
       
       def next(self):
           if not self.position and self.crossover > 0:
               self.buy()  # 金叉买入
           elif self.position and self.crossover < 0:
               self.close()  # 死叉卖出

   cerebro = bt.Cerebro()
   data = bt.feeds.GenericCSVData(dataname='data.csv',
       datetime=0, open=1, high=2, low=3, close=4, volume=5,
       dtformat='%Y-%m-%d')
   cerebro.adddata(data)
   cerebro.addstrategy(SmaCrossStrategy)
   cerebro.broker.setcash(100000)  # 初始资金
   cerebro.broker.setcommission(commission=0.001)  # 手续费
   
   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
   
   results = cerebro.run()
   strat = results[0]
   print(f"夏普比率: {strat.analyzers.sharpe.get_analysis().get('sharperatio', 'N/A')}")
   cerebro.plot(backend='plotly')

.. toctree::
   :maxdepth: 2
   :caption: 快速入门

   user_guide_zh/installation
   user_guide_zh/quickstart
   user_guide_zh/concepts

.. toctree::
   :maxdepth: 2
   :caption: 核心组件

   user_guide_zh/data_feeds
   user_guide_zh/strategies
   user_guide_zh/indicators
   user_guide_zh/brokers
   user_guide_zh/analyzers

.. toctree::
   :maxdepth: 2
   :caption: 进阶主题

   user_guide_zh/optimization
   user_guide_zh/visualization
   user_guide_zh/live_trading
   user_guide_zh/performance
   user_guide_zh/faq
   user_guide_zh/blog_index

API 参考
--------

API 文档基于源代码自动生成，请参阅 `英文版本的 API 参考文档 <api/modules.html>`_。

.. toctree::
   :maxdepth: 1
   :caption: 开发指南

   dev_zh/contributing
   dev_zh/changelog

索引和表格
==========

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
