.. Backtrader documentation master file

=======================================
Backtrader Documentation
=======================================

|github| |gitee| |python| |license|

.. |github| image:: https://img.shields.io/badge/GitHub-cloudQuant%2Fbacktrader-blue?logo=github
   :target: https://github.com/cloudQuant/backtrader
   :alt: GitHub

.. |gitee| image:: https://img.shields.io/badge/Gitee-yunjinqi%2Fbacktrader-red?logo=gitee
   :target: https://gitee.com/yunjinqi/backtrader
   :alt: Gitee

.. |python| image:: https://img.shields.io/badge/Python-3.7+-green?logo=python
   :alt: Python

.. |license| image:: https://img.shields.io/badge/License-GPLv3-orange
   :alt: License

**Backtrader** is a feature-rich Python framework for backtesting and trading,
supporting multiple data feeds, brokers, and analysis tools.

.. note::
   This documentation is available in both English and Chinese (中文).

Getting Started
---------------

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
   :caption: User Guide

   user_guide/installation
   user_guide/quickstart
   user_guide/concepts
   user_guide/data_feeds
   user_guide/strategies
   user_guide/indicators
   user_guide/analyzers
   user_guide/optimization

.. toctree::
   :maxdepth: 3
   :caption: API Reference

   api/modules

.. toctree::
   :maxdepth: 1
   :caption: Development

   dev/contributing
   dev/changelog

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
