==========
Indicators
==========

Indicators calculate derived values from price data. Backtrader provides 100+
built-in indicators and supports TA-Lib integration.

.. tip::
   Always declare indicators in ``__init__`` for best performance. This allows
   vectorized calculation before ``next()`` is called.

Indicator Sources
-----------------

Backtrader supports three types of indicators:

1. **Built-in indicators**: `bt.indicators <https://www.backtrader.com/docu/indautoref/>`_
2. **TA-Lib indicators**: `bt.talib <https://www.backtrader.com/docu/talibindautoref/>`_
3. **Custom indicators**: User-defined

.. warning::
   When using TA-Lib indicators, always verify the results match your expectations.
   Some TA-Lib calculations may differ from Backtrader's built-in versions.

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

Using TA-Lib Indicators
-----------------------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def __init__(self):
           # TA-Lib SMA (note: uses 'timeperiod' instead of 'period')
           self.sma = bt.talib.SMA(self.data.close, timeperiod=20)
           
           # TA-Lib MACD
           self.macd = bt.talib.MACD(self.data.close)
           
           # TA-Lib Bollinger Bands
           self.bbands = bt.talib.BBANDS(self.data.close, timeperiod=20)

Multi-Data Indicators
---------------------

For strategies with multiple data feeds, use dictionaries to store indicators:

.. code-block:: python

   class MultiDataStrategy(bt.Strategy):
       params = (('period', 20),)
       
       def __init__(self):
           # Store indicators for each data feed
           self.sma_dict = {
               data._name: bt.indicators.SMA(data.close, period=self.p.period)
               for data in self.datas
           }
       
       def next(self):
           for data in self.datas:
               sma = self.sma_dict[data._name]
               if data.close[0] > sma[0]:
                   self.buy(data=data)

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
           subplot=True,       # Separate subplot (False = overlay on price)
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

Plotting Intermediate Variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Regular indicator results plot automatically. Intermediate variables need explicit declaration:

.. code-block:: python

   from backtrader.indicators import LinePlotterIndicator
   
   class MyStrategy(bt.Strategy):
       def __init__(self):
           sma = bt.indicators.SMA(self.data.close, period=20)
           ema = bt.indicators.EMA(self.data.close, period=20)
           
           # This intermediate variable won't plot by default
           close_over_sma = self.data.close > sma
           
           # Use LinePlotterIndicator to plot it
           LinePlotterIndicator(close_over_sma, name='Close_over_SMA')

Controlling Plot Location
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   # Plot on price chart (subplot=False) or separate (subplot=True)
   self.sma = bt.indicators.SMA(
       self.data.close,
       period=20,
       subplot=False,      # Overlay on price chart
       plotname='SMA 20'   # Custom name in legend
   )

Best Practices
--------------

1. **Declare in __init__**: Indicators declared in ``__init__`` are calculated vectorized (faster)
2. **Use built-in operations**: Prefer ``bt.indicators.SMA`` over manual loops
3. **Verify TA-Lib results**: Cross-check TA-Lib calculations with expected values
4. **Use dictionaries for multi-data**: Store indicators per data feed for easy access

See Also
--------

- :doc:`concepts` - Lines data structure
- :doc:`strategies` - Using indicators in strategies
- `Built-in Indicators Reference <https://www.backtrader.com/docu/indautoref/>`_
- `TA-Lib Indicators Reference <https://www.backtrader.com/docu/talibindautoref/>`_
