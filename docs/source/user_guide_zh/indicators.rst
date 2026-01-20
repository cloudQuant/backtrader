========
技术指标
========

指标从价格数据中计算衍生值。Backtrader 提供 100+ 内置指标，
并支持 TA-Lib 集成。

.. tip::
   始终在 ``__init__`` 中声明指标以获得最佳性能。这样可以在调用 ``next()``
   之前进行向量化计算。

指标来源
--------

Backtrader 支持三种类型的指标：

1. **内置指标**: `bt.indicators <https://www.backtrader.com/docu/indautoref/>`_
2. **TA-Lib 指标**: `bt.talib <https://www.backtrader.com/docu/talibindautoref/>`_
3. **自定义指标**: 用户自定义

.. warning::
   使用 TA-Lib 指标时，始终验证结果是否符合预期。
   某些 TA-Lib 计算可能与 Backtrader 内置版本不同。

使用内置指标
------------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def __init__(self):
           # 移动平均线
           self.sma = bt.indicators.SMA(self.data.close, period=20)
           self.ema = bt.indicators.EMA(self.data.close, period=20)
           
           # 动量指标
           self.rsi = bt.indicators.RSI(self.data.close, period=14)
           self.macd = bt.indicators.MACD(self.data.close)
           
           # 波动率指标
           self.atr = bt.indicators.ATR(self.data, period=14)
           self.bbands = bt.indicators.BollingerBands(self.data.close)
           
           # 交叉信号
           self.crossover = bt.indicators.CrossOver(self.sma, self.ema)

使用 TA-Lib 指标
----------------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def __init__(self):
           # TA-Lib SMA（注意：使用 'timeperiod' 而不是 'period'）
           self.sma = bt.talib.SMA(self.data.close, timeperiod=20)
           
           # TA-Lib MACD
           self.macd = bt.talib.MACD(self.data.close)
           
           # TA-Lib 布林带
           self.bbands = bt.talib.BBANDS(self.data.close, timeperiod=20)

多数据指标
----------

对于多数据源的策略，使用字典存储指标：

.. code-block:: python

   class MultiDataStrategy(bt.Strategy):
       params = (('period', 20),)
       
       def __init__(self):
           # 为每个数据源存储指标
           self.sma_dict = {
               data._name: bt.indicators.SMA(data.close, period=self.p.period)
               for data in self.datas
           }
       
       def next(self):
           for data in self.datas:
               sma = self.sma_dict[data._name]
               if data.close[0] > sma[0]:
                   self.buy(data=data)

创建自定义指标
--------------

简单自定义指标
~~~~~~~~~~~~~~

.. code-block:: python

   class MyIndicator(bt.Indicator):
       lines = ('signal',)
       params = (('period', 20),)
       
       def __init__(self):
           self.addminperiod(self.p.period)
       
       def next(self):
           # 计算值
           values = self.data.close.get(size=self.p.period)
           self.lines.signal[0] = sum(values) / self.p.period

向量化指标（更快）
~~~~~~~~~~~~~~~~~~

.. code-block:: python

   class MyFastIndicator(bt.Indicator):
       lines = ('signal',)
       params = (('period', 20),)
       
       def __init__(self):
           # 使用内置运算
           self.lines.signal = bt.indicators.SMA(
               self.data.close, period=self.p.period
           )

多线指标
~~~~~~~~

.. code-block:: python

   class MyBands(bt.Indicator):
       lines = ('mid', 'top', 'bot')
       params = (('period', 20), ('devfactor', 2.0))
       
       def __init__(self):
           self.lines.mid = bt.indicators.SMA(
               self.data.close, period=self.p.period
           )
           stddev = bt.indicators.StdDev(
               self.data.close, period=self.p.period
           )
           self.lines.top = self.lines.mid + self.p.devfactor * stddev
           self.lines.bot = self.lines.mid - self.p.devfactor * stddev

指标运算
--------

.. code-block:: python

   # 算术运算
   diff = self.data.close - self.sma
   ratio = self.data.close / self.sma
   
   # 逻辑运算
   above = self.data.close > self.sma
   below = self.data.close < self.sma
   
   # 组合指标
   combined = bt.And(
       self.data.close > self.sma,
       self.rsi < 30
   )

指标绘图
--------

.. code-block:: python

   class MyIndicator(bt.Indicator):
       lines = ('signal',)
       
       plotinfo = dict(
           plot=True,
           subplot=True,       # 单独子图（False = 叠加在价格图上）
           plotname='我的信号',
           plotlinevalues=True,
       )
       
       plotlines = dict(
           signal=dict(
               color='blue',
               linewidth=1.0,
               _plotskip=False,
           ),
       )

绘制中间变量
~~~~~~~~~~~~

普通指标结果会自动绘制。中间变量需要显式声明：

.. code-block:: python

   from backtrader.indicators import LinePlotterIndicator
   
   class MyStrategy(bt.Strategy):
       def __init__(self):
           sma = bt.indicators.SMA(self.data.close, period=20)
           ema = bt.indicators.EMA(self.data.close, period=20)
           
           # 这个中间变量默认不会绘制
           close_over_sma = self.data.close > sma
           
           # 使用 LinePlotterIndicator 绘制它
           LinePlotterIndicator(close_over_sma, name='Close_over_SMA')

控制绘图位置
~~~~~~~~~~~~

.. code-block:: python

   # 在价格图上绘制（subplot=False）或单独子图（subplot=True）
   self.sma = bt.indicators.SMA(
       self.data.close,
       period=20,
       subplot=False,      # 叠加在价格图上
       plotname='SMA 20'   # 图例中的自定义名称
   )

最佳实践
--------

1. **在 __init__ 中声明**: 在 ``__init__`` 中声明的指标会向量化计算（更快）
2. **使用内置运算**: 优先使用 ``bt.indicators.SMA`` 而不是手动循环
3. **验证 TA-Lib 结果**: 交叉校验 TA-Lib 计算结果
4. **多数据使用字典**: 按数据源存储指标便于访问

参见
----

- :doc:`concepts` - Lines 数据结构
- :doc:`strategies` - 在策略中使用指标
- `内置指标参考 <https://www.backtrader.com/docu/indautoref/>`_
- `TA-Lib 指标参考 <https://www.backtrader.com/docu/talibindautoref/>`_
