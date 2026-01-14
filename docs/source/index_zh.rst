.. Backtrader 文档主页

=======================================
Backtrader 文档
=======================================

|github| |gitee| |python| |license|

.. |github| image:: https://img.shields.io/badge/GitHub-cloudquant%2Fbacktrader-blue?logo=github
   :target: https://github.com/cloudquant/backtrader
   :alt: GitHub

.. |gitee| image:: https://img.shields.io/badge/Gitee-cloudquant%2Fbacktrader-red?logo=gitee
   :target: https://gitee.com/cloudquant/backtrader
   :alt: Gitee

.. |python| image:: https://img.shields.io/badge/Python-3.7+-green?logo=python
   :alt: Python

.. |license| image:: https://img.shields.io/badge/License-GPLv3-orange
   :alt: License

**Backtrader** 是一个功能丰富的Python量化交易框架，支持回测和实盘交易，
提供多种数据源、经纪商和分析工具。

.. note::
   本文档提供中文和英文两种语言版本。

快速开始
--------

.. code-block:: python

   import backtrader as bt

   class MyStrategy(bt.Strategy):
       def __init__(self):
           self.sma = bt.indicators.SMA(self.data.close, period=20)
       
       def next(self):
           if self.data.close[0] > self.sma[0]:
               self.buy()
           elif self.data.close[0] < self.sma[0]:
               self.sell()

   cerebro = bt.Cerebro()
   data = bt.feeds.GenericCSVData(dataname='data.csv')
   cerebro.adddata(data)
   cerebro.addstrategy(MyStrategy)
   cerebro.broker.setcash(100000)
   results = cerebro.run()
   cerebro.plot()

.. toctree::
   :maxdepth: 2
   :caption: 用户指南

   user_guide_zh/installation
   user_guide_zh/quickstart
   user_guide_zh/concepts
   user_guide_zh/data_feeds
   user_guide_zh/strategies
   user_guide_zh/indicators
   user_guide_zh/analyzers
   user_guide_zh/optimization

API 参考
--------

API 文档基于源代码自动生成，请参阅英文版本的 API 参考文档。

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
