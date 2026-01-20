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

.. |python| image:: https://img.shields.io/badge/Python-3.9+-green?logo=python
   :alt: Python

.. |license| image:: https://img.shields.io/badge/License-GPLv3-orange
   :alt: License

**Backtrader** is a feature-rich Python framework for backtesting and trading,
supporting 50+ technical indicators, 20+ data sources, multiple brokers and comprehensive analysis tools.

.. note::
   This documentation is available in both English and `Chinese (中文) <index_zh.html>`_.
   
   Author's Blog: `https://yunjinqi.blog.csdn.net/ <https://yunjinqi.blog.csdn.net/>`_

Why Choose Backtrader?
-----------------------

- **Easy to Learn**: Gentle learning curve with intuitive API design
- **High Performance**: Supports vectorized (runonce) and event-driven (runnext) modes
- **Rich Components**: 50+ indicators, 17+ analyzers, 21+ data sources
- **Professional Visualization**: Plotly, Bokeh, and Matplotlib support
- **Live Trading Ready**: Integration with Interactive Brokers, CCXT, and more
- **Comprehensive Reports**: One-click HTML/PDF/JSON report generation

Quick Start
-----------

.. code-block:: python

   import backtrader as bt

   class SmaCrossStrategy(bt.Strategy):
       params = (('fast', 10), ('slow', 30))
       
       def __init__(self):
           fast_sma = bt.indicators.SMA(period=self.params.fast)
           slow_sma = bt.indicators.SMA(period=self.params.slow)
           self.crossover = bt.indicators.CrossOver(fast_sma, slow_sma)
       
       def next(self):
           if not self.position and self.crossover > 0:
               self.buy()
           elif self.position and self.crossover < 0:
               self.close()

   cerebro = bt.Cerebro()
   data = bt.feeds.GenericCSVData(dataname='data.csv',
       datetime=0, open=1, high=2, low=3, close=4, volume=5,
       dtformat='%Y-%m-%d')
   cerebro.adddata(data)
   cerebro.addstrategy(SmaCrossStrategy)
   cerebro.broker.setcash(100000)
   cerebro.broker.setcommission(commission=0.001)
   
   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
   
   results = cerebro.run()
   strat = results[0]
   print(f"Sharpe Ratio: {strat.analyzers.sharpe.get_analysis().get('sharperatio', 'N/A')}")
   cerebro.plot(backend='plotly')

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   user_guide/installation
   user_guide/quickstart
   user_guide/concepts

.. toctree::
   :maxdepth: 2
   :caption: Core Components

   user_guide/data_feeds
   user_guide/strategies
   user_guide/indicators
   user_guide/brokers
   user_guide/analyzers

.. toctree::
   :maxdepth: 2
   :caption: Advanced Topics

   user_guide/optimization
   user_guide/visualization
   user_guide/live_trading
   user_guide/performance
   user_guide/faq
   user_guide/blog_index

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
