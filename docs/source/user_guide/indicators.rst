==========
Indicators
==========

Using Built-in Indicators
-------------------------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def __init__(self):
           # Moving averages
           self.sma = bt.indicators.SMA(self.data.close, period=20)
           self.ema = bt.indicators.EMA(self.data.close, period=20)
           
           # Momentum
           self.rsi = bt.indicators.RSI(self.data.close, period=14)
           self.macd = bt.indicators.MACD(self.data.close)
           
           # Volatility
           self.atr = bt.indicators.ATR(self.data, period=14)
           self.bbands = bt.indicators.BollingerBands(self.data.close)
           
           # Crossovers
           self.crossover = bt.indicators.CrossOver(self.sma, self.ema)

Creating Custom Indicators
--------------------------

Simple Custom Indicator
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   class MyIndicator(bt.Indicator):
       lines = ('signal',)
       params = (('period', 20),)
       
       def __init__(self):
           self.addminperiod(self.p.period)
       
       def next(self):
           # Calculate value
           values = self.data.close.get(size=self.p.period)
           self.lines.signal[0] = sum(values) / self.p.period

Vectorized Indicator (Faster)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   class MyFastIndicator(bt.Indicator):
       lines = ('signal',)
       params = (('period', 20),)
       
       def __init__(self):
           # Use built-in operations
           self.lines.signal = bt.indicators.SMA(
               self.data.close, period=self.p.period
           )

Multi-Line Indicator
~~~~~~~~~~~~~~~~~~~~

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

Indicator Operations
--------------------

.. code-block:: python

   # Arithmetic operations
   diff = self.data.close - self.sma
   ratio = self.data.close / self.sma
   
   # Logical operations
   above = self.data.close > self.sma
   below = self.data.close < self.sma
   
   # Combine indicators
   combined = bt.And(
       self.data.close > self.sma,
       self.rsi < 30
   )

Plotting Indicators
-------------------

.. code-block:: python

   class MyIndicator(bt.Indicator):
       lines = ('signal',)
       
       plotinfo = dict(
           plot=True,
           subplot=True,       # Separate subplot
           plotname='My Signal',
           plotlinevalues=True,
       )
       
       plotlines = dict(
           signal=dict(
               color='blue',
               linewidth=1.0,
               _plotskip=False,
           ),
       )
