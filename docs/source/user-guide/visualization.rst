==========
可视化系统
==========

Backtrader 提供多种可视化后端来分析回测结果，包括用于交互式图表的 Plotly、
用于实时更新的 Bokeh 以及用于静态出版级图表的 Matplotlib。

快速开始
--------

.. code-block:: python

   cerebro = bt.Cerebro()
   # ... 设置策略和数据 ...
   results = cerebro.run()
   
   # 默认 matplotlib 绑图
   cerebro.plot()
   
   # 交互式 Plotly 图表
   cerebro.plot(backend='plotly')
   
   # Bokeh 图表
   cerebro.plot(backend='bokeh')

Plotly 后端（推荐）
-------------------

Plotly 创建具有缩放、平移和悬停功能的交互式 HTML 图表。

基本用法
^^^^^^^^

.. code-block:: python

   # 交互式绑图
   cerebro.plot(backend='plotly', style='candle')
   
   # 自定义外观
   cerebro.plot(
       backend='plotly',
       style='candle',           # 'candle'、'bar'、'line'
       barup='green',
       bardown='red',
       volup='lightgreen',
       voldown='lightcoral'
   )

保存为 HTML
^^^^^^^^^^^

.. code-block:: python

   from backtrader.plot import PlotlyPlot
   
   # 创建绑图器
   plotter = PlotlyPlot(style='candle')
   
   # 生成图形
   figs = plotter.plot(results[0])
   
   # 保存为 HTML 文件
   figs[0].write_html('backtest_chart.html')
   
   # 保存为静态图片（需要 kaleido）
   figs[0].write_image('backtest_chart.png', width=1920, height=1080)

大数据集处理
^^^^^^^^^^^^

Plotly 可以高效处理 100k+ 数据点的大型数据集：

.. code-block:: python

   cerebro.plot(
       backend='plotly',
       style='candle',
       numfigs=1,                # 单个图形
       plotdist=0.1,             # 子图间距
   )

Bokeh 后端
----------

Bokeh 提供具有实时更新功能的交互式图表。

.. code-block:: python

   # 基本 Bokeh 绑图
   cerebro.plot(backend='bokeh')
   
   # 输出到文件
   from bokeh.io import output_file, save
   output_file('backtest.html')
   figs = cerebro.plot(backend='bokeh')

Matplotlib 后端
---------------

Matplotlib 创建静态的出版级图表。

基本绑图
^^^^^^^^

.. code-block:: python

   import matplotlib.pyplot as plt
   
   # 默认绑图
   cerebro.plot()
   
   # 蜡烛图样式
   cerebro.plot(style='candle')
   
   # 折线图
   cerebro.plot(style='line')
   
   # 柱状图（OHLC）
   cerebro.plot(style='bar')

自定义设置
^^^^^^^^^^

.. code-block:: python

   cerebro.plot(
       style='candle',
       barup='green',
       bardown='red',
       volup='lightgreen',
       voldown='lightcoral',
       fmt_x_data='%Y-%m-%d',
       fmt_x_ticks='%b %d',
       plotdist=0.5,
       numfigs=1,
       width=16,
       height=9,
       dpi=100,
       tight=True
   )

保存图形
^^^^^^^^

.. code-block:: python

   import matplotlib.pyplot as plt
   
   cerebro.plot(style='candle')
   plt.savefig('backtest.png', dpi=300, bbox_inches='tight')
   plt.savefig('backtest.pdf', bbox_inches='tight')

指标可视化
----------

配置指标显示
^^^^^^^^^^^^

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def __init__(self):
           # 在主图显示的指标
           self.sma = bt.indicators.SMA(period=20)
           self.sma.plotinfo.plotmaster = self.data
           
           # 在子图显示的指标
           self.rsi = bt.indicators.RSI(period=14)
           self.rsi.plotinfo.subplot = True
           
           # 自定义线条样式
           self.bbands = bt.indicators.BollingerBands()
           self.bbands.plotlines.top._plotskip = False
           self.bbands.plotlines.mid.color = 'blue'
           self.bbands.plotlines.bot.linestyle = '--'

自定义指标绑图
^^^^^^^^^^^^^^

.. code-block:: python

   class MyIndicator(bt.Indicator):
       lines = ('signal',)
       
       plotinfo = dict(
           plot=True,
           subplot=True,
           plotname='我的信号',
           plotabove=False,
           plotlinelabels=True
       )
       
       plotlines = dict(
           signal=dict(
               _name='信号',
               color='blue',
               linewidth=1.5,
               linestyle='-'
           )
       )

观察者可视化
------------

观察者在图表上显示交易信息：

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # 添加内置观察者
   cerebro.addobserver(bt.observers.BuySell)      # 买卖标记
   cerebro.addobserver(bt.observers.Trades)       # 交易盈亏
   cerebro.addobserver(bt.observers.Value)        # 投资组合价值
   cerebro.addobserver(bt.observers.DrawDown)     # 回撤
   cerebro.addobserver(bt.observers.Cash)         # 现金水平
   
   # 自定义观察者外观
   cerebro.addobserver(
       bt.observers.BuySell,
       barplot=True,
       bardist=0.015
   )

多数据可视化
------------

.. code-block:: python

   cerebro = bt.Cerebro()
   cerebro.adddata(data1, name='股票1')
   cerebro.adddata(data2, name='股票2')
   
   results = cerebro.run()
   
   # 在不同图形中绑制所有数据
   cerebro.plot(numfigs=2)
   
   # 绑制特定数据
   cerebro.plot(plotdata=[0])  # 仅第一个数据

专业报告
--------

生成全面的 HTML 报告：

.. code-block:: python

   # 添加报告分析器
   cerebro.add_report_analyzers(riskfree_rate=0.02)
   
   # 运行回测
   results = cerebro.run()
   
   # 生成报告
   cerebro.generate_report(
       filename='report.html',
       user='交易员',
       memo='SMA 金叉死叉策略回测',
       strategy_name='SMA Cross'
   )

报告内容
^^^^^^^^

- **汇总统计**：总收益率、夏普比率、最大回撤
- **资金曲线**：投资组合价值随时间变化
- **回撤图表**：回撤百分比随时间变化
- **交易分析**：胜率、盈利因子、平均交易
- **月度收益**：月度绩效热力图
- **持仓分析**：交易入场/出场详情

绑图配置参考
------------

plotinfo 选项
^^^^^^^^^^^^^

.. list-table::
   :widths: 20 15 65
   :header-rows: 1

   * - 选项
     - 默认值
     - 描述
   * - plot
     - True
     - 启用/禁用绑图
   * - subplot
     - False
     - 在单独子图中绑制
   * - plotmaster
     - None
     - 一起绑制的数据
   * - plotname
     - ''
     - 自定义绑图名称
   * - plotabove
     - False
     - 在主图上方绑制
   * - plotlinelabels
     - False
     - 显示线条标签

样式选项
^^^^^^^^

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - 样式
     - 描述
   * - candle
     - 日本蜡烛图
   * - bar
     - OHLC 柱状图
   * - line
     - 折线图（收盘价）

最佳实践
--------

1. **性能**：对于大数据集（>10k 根K线）使用 Plotly
2. **出版**：对于论文和报告使用 Matplotlib
3. **开发**：对于实时/实盘开发使用 Bokeh
4. **报告**：使用 ``generate_report()`` 进行全面分析

参见
----

- :doc:`analyzers` - 绩效分析
- :doc:`strategies` - 策略开发
