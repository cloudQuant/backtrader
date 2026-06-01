.. Backtrader 中文文档

=======================================
Backtrader 中文文档
=======================================

.. raw:: html

   <div class="badges">
     <a href="https://github.com/cloudQuant/backtrader"><img src="https://img.shields.io/badge/GitHub-cloudQuant%2Fbacktrader-blue?logo=github" alt="GitHub"></a>
     <a href="https://gitee.com/yunjinqi/backtrader"><img src="https://img.shields.io/badge/Gitee-yunjinqi%2Fbacktrader-C71D23?logo=gitee" alt="Gitee"></a>
     <img src="https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white" alt="Python">
     <img src="https://img.shields.io/badge/License-GPLv3-orange" alt="License">
     <img src="https://img.shields.io/badge/文档-English%20%7C%20中文-1565C0" alt="i18n">
   </div>

**Backtrader** 是一个功能丰富的 Python 量化交易框架，支持回测和实盘交易，
提供 50+ 技术指标、20+ 数据源、多种经纪商和全面的分析工具。

.. tip::
   📖 本文档同时提供 `English (英文) <index.html>`_ 版本。

   ✍️ 作者博客: `yunjinqi.blog.csdn.net <https://yunjinqi.blog.csdn.net/>`_

----

为什么选择 Backtrader？
-----------------------

.. grid:: 2 2 3 3
   :gutter: 3

   .. grid-item-card:: 📚 易于学习
      :class-card: sd-border-0 sd-shadow-sm

      学习曲线平缓，API 设计直观。
      5 分钟即可运行你的第一个策略。

   .. grid-item-card:: ⚡ 高性能
      :class-card: sd-border-0 sd-shadow-sm

      支持向量化 (``runonce``) 和事件驱动 (``runnext``)
      两种模式，比原版快 45% 以上。

   .. grid-item-card:: 🧩 组件丰富
      :class-card: sd-border-0 sd-shadow-sm

      50+ 指标、17+ 分析器、21+ 数据源 —
      开箱即用，满足各种需求。

   .. grid-item-card:: 📊 专业可视化
      :class-card: sd-border-0 sd-shadow-sm

      支持 Plotly、Bokeh、Matplotlib，
      一键生成 HTML/PDF/JSON 报告。

   .. grid-item-card:: 🌐 实盘就绪
      :class-card: sd-border-0 sd-shadow-sm

      支持盈透证券 (IB)、
      CTP (中国期货) — 回测到实盘无缝切换。

   .. grid-item-card:: 🔧 高度可扩展
      :class-card: sd-border-0 sd-shadow-sm

      自定义指标、分析器、数据源和经纪商。
      插件友好的架构设计。

----

快速开始
--------

.. tab-set::

   .. tab-item:: 安装

      .. code-block:: bash

         git clone https://github.com/cloudQuant/backtrader.git
         cd backtrader && pip install -U .

   .. tab-item:: 策略示例

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
                     self.buy()   # 金叉买入
                 elif self.position and self.crossover < 0:
                     self.close() # 死叉卖出

   .. tab-item:: 运行回测

      .. code-block:: python

         cerebro = bt.Cerebro()
         data = bt.feeds.GenericCSVData(
             dataname='data.csv',
             datetime=0, open=1, high=2, low=3,
             close=4, volume=5, dtformat='%Y-%m-%d')

         cerebro.adddata(data)
         cerebro.addstrategy(SmaCross)
         cerebro.broker.setcash(100000)          # 初始资金
         cerebro.broker.setcommission(commission=0.001)  # 手续费

         cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
         cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

         results = cerebro.run()
         strat = results[0]
         print(f"夏普比率: {strat.analyzers.sharpe.get_analysis()}")
         cerebro.plot(backend='plotly')

----

源代码
------

.. grid:: 1 1 2 2
   :gutter: 3

   .. grid-item-card:: GitHub
      :link: https://github.com/cloudQuant/backtrader
      :class-card: sd-border-0 sd-shadow-sm

      主仓库 — Issues、Pull Requests、CI/CD。

   .. grid-item-card:: Gitee (国内镜像)
      :link: https://gitee.com/yunjinqi/backtrader
      :class-card: sd-border-0 sd-shadow-sm

      国内镜像，访问更快速、更稳定。

----

.. toctree::
   :maxdepth: 2
   :caption: 快速入门

   getting-started/installation_zh
   getting-started/quickstart_zh

.. toctree::
   :maxdepth: 2
   :caption: 核心组件

   user-guide/concepts/concepts_zh
   user-guide/data-feeds/data-feeds_zh
   user-guide/strategies/strategies_zh
   user-guide/indicators/indicators_zh
   user-guide/analyzers/analyzers_zh
   user-guide/analyzers/observers_zh
   user-guide/visualization/plotting_zh
   user-guide/optimization/optimization_zh

.. toctree::
   :maxdepth: 2
   :caption: 进阶主题

   advanced/ts-mode_zh
   advanced/cs-mode_zh
   advanced/multi-strategy_zh
   advanced/performance-optimization_zh
   advanced/profiling_zh
   advanced/data-acquisition_zh
   advanced/architecture/overview_zh
   advanced/architecture/line-system_zh
   advanced/architecture/phase-system_zh
   user-guide/data-feeds/live/ctp-live-trading_zh

.. toctree::
   :maxdepth: 2
   :caption: 教程

   tutorials/complete-strategy_zh
   tutorials/notebook-guide_zh
   tutorials/examples/strategies_zh
   tutorials/examples/cookbook_zh

.. only:: not offline

   .. toctree::
      :maxdepth: 1
      :caption: API 参考

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
   :caption: 迁移指南

   migration/from-original_zh
   migration/upgrade_zh

.. toctree::
   :maxdepth: 1
   :caption: 开发者指南

   developer-guide/index_zh
   developer-guide/setup_zh
   developer-guide/testing_zh
   developer-guide/style_zh
   developer-guide/contributing_zh
   developer-guide/release_zh

.. toctree::
   :maxdepth: 1
   :caption: 支持

   reference/support/faq_zh
   reference/support/troubleshooting_zh

----

索引和表格
==========

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
