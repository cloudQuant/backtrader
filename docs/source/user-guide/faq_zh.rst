============
常见问题解答
============

本节涵盖使用 Backtrader 时遇到的常见问题和解决方案。

安装与设置
----------

问：如何安装 Backtrader？
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   # 从 GitHub 克隆
   git clone https://github.com/cloudQuant/backtrader.git
   cd backtrader
   pip install -r requirements.txt
   pip install -e .
   
   # 或从 Gitee 克隆（国内用户推荐）
   git clone https://gitee.com/yunjinqi/backtrader.git

问：应该使用哪个 Python 版本？
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

需要 Python 3.9+。推荐使用 Python 3.11+ 以获得约 15% 的性能提升。

问：Backtrader 无法在我的系统上安装
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

常见解决方案：

.. code-block:: bash

   # 更新 pip
   pip install --upgrade pip
   
   # 使用 user 标志安装
   pip install -e . --user
   
   # 使用虚拟环境
   python -m venv bt_env
   source bt_env/bin/activate  # Linux/Mac
   bt_env\Scripts\activate     # Windows
   pip install -e .

数据问题
--------

问：我的 CSV 数据无法正确加载
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

检查日期格式和列顺序：

.. code-block:: python

   data = bt.feeds.GenericCSVData(
       dataname='data.csv',
       datetime=0,      # 日期时间列索引
       open=1,
       high=2,
       low=3,
       close=4,
       volume=5,
       openinterest=-1, # -1 表示不存在
       dtformat='%Y-%m-%d',  # 日期格式
       tmformat='%H:%M:%S',  # 时间格式（如果需要）
   )

问：如何使用 Pandas DataFrame 作为数据源？
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   import pandas as pd
   import backtrader as bt
   
   df = pd.read_csv('data.csv', parse_dates=['date'], index_col='date')
   data = bt.feeds.PandasData(dataname=df)
   cerebro.adddata(data)

问：如何处理缺失数据？
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # 加载前在 pandas 中填充缺失值
   df = df.fillna(method='ffill')  # 前向填充
   
   # 或删除缺失行
   df = df.dropna()

策略问题
--------

问：我的策略没有执行任何交易
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

常见原因：

1. **资金不足**：检查 ``cerebro.broker.setcash()``
2. **指标预热期**：指标计算所需的数据不足
3. **逻辑错误**：检查买卖条件

.. code-block:: python

   def next(self):
       # 调试输出
       print(f'日期: {self.data.datetime.date(0)}')
       print(f'收盘价: {self.data.close[0]}')
       print(f'SMA: {self.sma[0]}')
       print(f'持仓: {self.position.size}')
       
       if not self.position:
           if self.data.close[0] > self.sma[0]:
               print('买入信号')
               self.buy()

问：为什么调用的是 prenext() 而不是 next()？
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``prenext()`` 在所有指标都有足够数据之前被调用。检查最长指标周期。

.. code-block:: python

   def __init__(self):
       self.sma50 = bt.indicators.SMA(period=50)  # 需要 50 根K线
   
   def prenext(self):
       # 前 49 根K线调用
       pass
   
   def next(self):
       # 从第 50 根K线开始调用
       pass

问：如何交易多个品种？
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   cerebro.adddata(data1, name='AAPL')
   cerebro.adddata(data2, name='GOOGL')
   
   class MultiStrategy(bt.Strategy):
       def next(self):
           for i, data in enumerate(self.datas):
               if not self.getposition(data):
                   if data.close[0] > data.close[-1]:
                       self.buy(data=data)

订单和经纪商问题
----------------

问：如何设置手续费和滑点？
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # 手续费 (0.1%)
   cerebro.broker.setcommission(commission=0.001)
   
   # 固定滑点
   cerebro.broker.set_slippage_fixed(fixed=0.01)
   
   # 百分比滑点
   cerebro.broker.set_slippage_perc(perc=0.0005)

问：为什么我的订单被拒绝？
^^^^^^^^^^^^^^^^^^^^^^^^^^

检查资金或保证金是否充足：

.. code-block:: python

   def notify_order(self, order):
       if order.status == order.Rejected:
           print(f'订单被拒绝 - 现金: {self.broker.getcash()}')
       elif order.status == order.Margin:
           print('保证金不足')

问：如何实现止损和止盈？
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # 方法1：括号订单
   self.buy_bracket(
       price=100.0,
       stopprice=95.0,   # 止损
       limitprice=110.0  # 止盈
   )
   
   # 方法2：手动跟踪
   def __init__(self):
       self.entry_price = None
   
   def next(self):
       if self.position and self.entry_price:
           pnl_pct = (self.data.close[0] - self.entry_price) / self.entry_price
           if pnl_pct < -0.05:  # -5% 止损
               self.close()
           elif pnl_pct > 0.10:  # +10% 止盈
               self.close()

指标问题
--------

问：如何访问前几根K线的指标值？
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # 当前K线
   current_sma = self.sma[0]
   
   # 前一根K线
   prev_sma = self.sma[-1]
   
   # 5根K线前
   old_sma = self.sma[-5]

问：如何创建自定义指标？
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   class MyIndicator(bt.Indicator):
       lines = ('myline',)
       params = (('period', 20),)
       
       def __init__(self):
           self.addminperiod(self.p.period)
       
       def next(self):
           self.lines.myline[0] = sum(self.data.get(size=self.p.period)) / self.p.period

性能问题
--------

问：回测速度太慢
^^^^^^^^^^^^^^^^

详细优化指南请参见 :doc:`performance`。快速技巧：

.. code-block:: python

   # 1. 使用向量化模式
   cerebro.run(runonce=True)  # 默认
   
   # 2. 使用 Python 3.11+
   
   # 3. 使用 pickle 而不是 CSV
   df.to_pickle('data.pkl')
   df = pd.read_pickle('data.pkl')
   
   # 4. 限制数据范围
   data = bt.feeds.GenericCSVData(
       dataname='data.csv',
       fromdate=datetime(2020, 1, 1),
       todate=datetime(2023, 12, 31)
   )

问：如何使用多 CPU 进行优化？
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   cerebro.optstrategy(
       MyStrategy,
       period=range(10, 50, 5)
   )
   results = cerebro.run(maxcpus=4)  # 使用 4 个 CPU

可视化问题
----------

问：如何将图表保存到文件？
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # Matplotlib
   import matplotlib.pyplot as plt
   cerebro.plot()
   plt.savefig('chart.png', dpi=300)
   
   # Plotly
   from backtrader.plot import PlotlyPlot
   plotter = PlotlyPlot()
   figs = plotter.plot(results[0])
   figs[0].write_html('chart.html')

问：如何隐藏某些指标不显示？
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   self.sma = bt.indicators.SMA(period=20)
   self.sma.plotinfo.plot = False  # 从图表中隐藏

分析问题
--------

问：如何获取夏普比率？
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
   results = cerebro.run()
   sharpe = results[0].analyzers.sharpe.get_analysis()
   print(f"夏普比率: {sharpe.get('sharperatio', 'N/A')}")

问：如何获取所有交易详情？
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
   cerebro.addanalyzer(bt.analyzers.Transactions, _name='txn')
   
   results = cerebro.run()
   trades = results[0].analyzers.trades.get_analysis()
   transactions = results[0].analyzers.txn.get_analysis()

问：如何计算最大回撤？
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
   results = cerebro.run()
   dd = results[0].analyzers.dd.get_analysis()
   print(f"最大回撤: {dd['max']['drawdown']:.2f}%")

多周期问题
----------

问：如何使用多个时间周期？
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # 添加基础数据（如1分钟）
   data0 = bt.feeds.GenericCSVData(dataname='data_1min.csv')
   cerebro.adddata(data0)
   
   # 重采样为更高周期
   cerebro.resampledata(data0, timeframe=bt.TimeFrame.Minutes, compression=5)
   cerebro.resampledata(data0, timeframe=bt.TimeFrame.Days, compression=1)
   
   class MultiTFStrategy(bt.Strategy):
       def next(self):
           # 访问不同周期
           data_1min = self.datas[0]
           data_5min = self.datas[1]
           data_daily = self.datas[2]

问：为什么我的重采样数据没有对齐？
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

这是一个常见问题。请参阅博客上关于多周期数据处理的文章：
https://yunjinqi.blog.csdn.net/

关键点：

- 较高周期的K线只有在下一根基础K线到达时才算完成
- 实盘交易中使用 ``cerebro.run(runonce=False)`` 以获得精确时序

获取帮助
--------

- **文档**：https://backtrader.readthedocs.io/
- **作者博客**：https://yunjinqi.blog.csdn.net/
- **GitHub Issues**：https://github.com/cloudQuant/backtrader/issues
- **Gitee Issues**：https://gitee.com/yunjinqi/backtrader/issues

参见
----

- :doc:`concepts` - 核心概念
- :doc:`strategies` - 策略开发
- :doc:`performance` - 性能优化
