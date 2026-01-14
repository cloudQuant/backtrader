====
指标
====

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

指标绑图
--------

.. code-block:: python

   class MyIndicator(bt.Indicator):
       lines = ('signal',)
       
       plotinfo = dict(
           plot=True,
           subplot=True,       # 单独子图
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
