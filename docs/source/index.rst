.. Backtrader Documentation

=======================================
Backtrader Documentation
=======================================

.. raw:: html

   <div class="badges">
     <a href="https://github.com/cloudQuant/backtrader"><img src="https://img.shields.io/badge/GitHub-cloudQuant%2Fbacktrader-blue?logo=github" alt="GitHub"></a>
     <a href="https://gitee.com/yunjinqi/backtrader"><img src="https://img.shields.io/badge/Gitee-yunjinqi%2Fbacktrader-C71D23?logo=gitee" alt="Gitee"></a>
     <img src="https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white" alt="Python">
     <img src="https://img.shields.io/badge/License-GPLv3-orange" alt="License">
     <img src="https://img.shields.io/badge/Docs-English%20%7C%20中文-1565C0" alt="i18n">
   </div>

**Backtrader** is a feature-rich Python quantitative trading framework supporting
backtesting and live trading, with 50+ technical indicators, multiple data sources,
various brokers, and comprehensive analysis tools.

.. tip::
   📖 This documentation is also available in `中文 (Chinese) <index_zh.html>`_.

   ✍️ Author's blog: `yunjinqi.blog.csdn.net <https://yunjinqi.blog.csdn.net/>`_

----

Why Backtrader?
---------------

.. grid:: 2 2 3 3
   :gutter: 3

   .. grid-item-card:: 📚 Easy to Learn
      :class-card: sd-border-0 sd-shadow-sm

      Gentle learning curve with intuitive API design.
      Get your first strategy running in 5 minutes.

   .. grid-item-card:: ⚡ High Performance
      :class-card: sd-border-0 sd-shadow-sm

      Vectorized (``runonce``) and event-driven (``runnext``)
      modes. 45%+ faster than the original.

   .. grid-item-card:: 🧩 Rich Components
      :class-card: sd-border-0 sd-shadow-sm

      50+ indicators, 17+ analyzers, 21+ data feeds —
      everything you need out of the box.

   .. grid-item-card:: 📊 Professional Visualization
      :class-card: sd-border-0 sd-shadow-sm

      Plotly, Bokeh, and Matplotlib backends with
      one-click HTML/PDF/JSON reports.

   .. grid-item-card:: 🌐 Live Trading Ready
      :class-card: sd-border-0 sd-shadow-sm

      Interactive Brokers, CCXT (crypto), and CTP
      (Chinese futures) — backtest to live seamlessly.

   .. grid-item-card:: 🔧 Extensible
      :class-card: sd-border-0 sd-shadow-sm

      Custom indicators, analyzers, data feeds, and
      brokers. Plugin-friendly architecture.

----

Quick Start
-----------

.. tab-set::

   .. tab-item:: Install

      .. code-block:: bash

         git clone https://github.com/cloudQuant/backtrader.git
         cd backtrader && pip install -U .

   .. tab-item:: Strategy Example

      .. code-block:: python

         import backtrader as bt

         class SmaCross(bt.Strategy):
             params = (('pfast', 10), ('pslow', 30))

             def __init__(self):
                 sma_fast = bt.indicators.SMA(period=self.p.pfast)
                 sma_slow = bt.indicators.SMA(period=self.p.pslow)
                 self.crossover = bt.indicators.CrossOver(sma_fast, sma_slow)

             def next(self):
                 if not self.position and self.crossover > 0:
                     self.buy()
                 elif self.position and self.crossover < 0:
                     self.close()

   .. tab-item:: Run Backtest

      .. code-block:: python

         cerebro = bt.Cerebro()
         data = bt.feeds.GenericCSVData(
             dataname='data.csv',
             datetime=0, open=1, high=2, low=3,
             close=4, volume=5, dtformat='%Y-%m-%d')

         cerebro.adddata(data)
         cerebro.addstrategy(SmaCross)
         cerebro.broker.setcash(100000)
         cerebro.broker.setcommission(commission=0.001)

         cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
         cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

         results = cerebro.run()
         strat = results[0]
         print(f"Sharpe: {strat.analyzers.sharpe.get_analysis()}")
         cerebro.plot(backend='plotly')

----

Source Code
-----------

.. grid:: 1 1 2 2
   :gutter: 3

   .. grid-item-card:: GitHub
      :link: https://github.com/cloudQuant/backtrader
      :class-card: sd-border-0 sd-shadow-sm

      Primary repository — issues, pull requests, CI/CD.

   .. grid-item-card:: Gitee (镜像)
      :link: https://gitee.com/yunjinqi/backtrader
      :class-card: sd-border-0 sd-shadow-sm

      Mirror for users in mainland China with faster access.

----

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   getting-started/installation
   getting-started/quickstart

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   user-guide/concepts/concepts
   user-guide/data-feeds/data-feeds
   user-guide/strategies/strategies
   user-guide/indicators/indicators
   user-guide/analyzers/analyzers
   user-guide/analyzers/observers
   user-guide/brokers/brokers
   user-guide/visualization/plotting
   user-guide/optimization/optimization
   user-guide/faq

.. toctree::
   :maxdepth: 2
   :caption: Advanced Topics

   advanced/ts-mode
   advanced/cs-mode
   advanced/multi-strategy
   advanced/performance-optimization
   advanced/profiling
   advanced/data-acquisition
   advanced/architecture/overview
   advanced/architecture/line-system
   advanced/architecture/phase-system
   advanced/architecture/post-metaclass
   advanced/live-trading/ccxt-guide
   advanced/live-trading/ccxt-env-config
   advanced/live-trading/websocket
   advanced/live-trading/funding-rate
   user-guide/data-feeds/live/ctp-live-trading

.. toctree::
   :maxdepth: 2
   :caption: Tutorials

   tutorials/complete-strategy
   tutorials/notebook-guide
   tutorials/examples/strategies
   tutorials/examples/cookbook

.. only:: not offline

   .. toctree::
      :maxdepth: 1
      :caption: API Reference

      api/core/backtrader
      api/analyzers/backtrader.analyzers
      api/feeds/backtrader.feeds
      api/indicators/backtrader.indicators
      api/brokers/backtrader.brokers
      api/observers/backtrader.observers
      api/sizers/backtrader.sizers
      api/stores/backtrader.stores

.. toctree::
   :maxdepth: 2
   :caption: Migration

   migration/from-original
   migration/upgrade

.. toctree::
   :maxdepth: 2
   :caption: Developer Guide

   developer-guide/index
   developer-guide/setup
   developer-guide/testing
   developer-guide/style
   developer-guide/contributing
   developer-guide/release

.. toctree::
   :maxdepth: 1
   :caption: Support

   reference/support/faq
   reference/support/troubleshooting

----

Indices and Tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
