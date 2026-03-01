=========
Indicator
=========

The ``Indicator`` class is the base class for all technical indicators.

.. automodule:: backtrader.indicator
   :members:
   :undoc-members:
   :show-inheritance:
   :no-index:

Overview
--------

Indicators calculate values from data feeds and can be used in strategies
for trading decisions. Backtrader includes many built-in indicators and
supports custom indicator creation.

Built-in Indicators
-------------------

Moving Averages
~~~~~~~~~~~~~~~

- ``SMA``: Simple Moving Average
- ``EMA``: Exponential Moving Average
- ``WMA``: Weighted Moving Average
- ``SMMA``: Smoothed Moving Average
- ``DEMA``: Double Exponential Moving Average
- ``TEMA``: Triple Exponential Moving Average

Momentum
~~~~~~~~

- ``RSI``: Relative Strength Index
- ``MACD``: Moving Average Convergence Divergence
- ``Stochastic``: Stochastic Oscillator
- ``ROC``: Rate of Change
- ``Momentum``: Momentum indicator
- ``CCI``: Commodity Channel Index

Volatility
~~~~~~~~~~

- ``ATR``: Average True Range
- ``BollingerBands``: Bollinger Bands
- ``StandardDeviation``: Standard Deviation

Trend
~~~~~

- ``ADX``: Average Directional Index
- ``Aroon``: Aroon Indicator
- ``ParabolicSAR``: Parabolic SAR

Volume
~~~~~~

- ``OBV``: On Balance Volume
- ``VWAP``: Volume Weighted Average Price

Creating Custom Indicators
--------------------------

.. code-block:: python

   class MyIndicator(bt.Indicator):
       lines = ('myline',)
       params = (('period', 20),)
       
       def __init__(self):
           self.addminperiod(self.params.period)
       
       def next(self):
           # Calculate indicator value
           self.lines.myline[0] = sum(
               self.data.close.get(size=self.params.period)
           ) / self.params.period

Using Indicators
----------------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def __init__(self):
           # Create indicators
           self.sma = bt.indicators.SMA(self.data.close, period=20)
           self.rsi = bt.indicators.RSI(self.data.close)
           self.macd = bt.indicators.MACD(self.data.close)
           
           # Combine indicators
           self.crossover = bt.indicators.CrossOver(
               self.data.close, self.sma
           )
       
       def next(self):
           if self.crossover > 0 and self.rsi < 30:
               self.buy()
