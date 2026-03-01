- --

title: Indicators
description: Built-in technical indicators

- --

# Indicators

Backtrader includes 60+ built-in technical indicators. This guide shows how to use them effectively.

## Basic Usage

```python
class MyStrategy(bt.Strategy):
    def __init__(self):

# Create indicator
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):

# Access current value
        current_value = self.sma[0]

```bash

## Indicator Categories

### Moving Averages

```python

# Simple Moving Average

sma = bt.indicators.SMA(self.data.close, period=20)

# Exponential Moving Average

ema = bt.indicators.EMA(self.data.close, period=20)

# Weighted Moving Average

wma = bt.indicators.WMA(self.data.close, period=20)

# Double Exponential Moving Average

dema = bt.indicators.DEMA(self.data.close, period=20)

# Triple Exponential Moving Average

tema = bt.indicators.TEMA(self.data.close, period=20)

# Hull Moving Average

hma = bt.indicators.HMA(self.data.close, period=20)

```bash

### Momentum Indicators

```python

# Relative Strength Index

rsi = bt.indicators.RSI(self.data.close, period=14)

# Stochastic

stoch = bt.indicators.Stochastic(self.data, period=14)

# MACD

macd = bt.indicators.MACD(self.data.close)

# Rate of Change

roc = bt.indicators.ROC(self.data.close, period=10)

# Momentum

momentum = bt.indicators.Momentum(self.data.close, period=10)

# Awesome Oscillator

ao = bt.indicators.AwesomeOscillator(self.data)

```bash

### Volatility Indicators

```python

# Average True Range

atr = bt.indicators.ATR(self.data, period=14)

# Bollinger Bands

bollinger = bt.indicators.BollingerBands(self.data.close, period=20)

# Standard Deviation

stdev = bt.indicators.StdDev(self.data.close, period=20)

```bash

### Volume Indicators

```python

# On-Balance Volume

obv = bt.indicators.OBV(self.data)

# Money Flow Index

mfi = bt.indicators.MFI(self.data, period=14)

```bash

### Oscillators

```python

# Commodity Channel Index

cci = bt.indicators.CCI(self.data, period=14)

# Directional Movement

plus_dm = bt.indicators.PlusDM(self.data, period=14)
minus_dm = bt.indicators.MinusDM(self.data, period=14)

# Average Directional Index

adx = bt.indicators.ADX(self.data, period=14)

# Aroon

aroon = bt.indicators.Aroon(self.data, period=14)

```bash

## CrossOver Indicator

Detect when one indicator crosses another.

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.fast_ma = bt.indicators.SMA(self.data.close, period=10)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=30)

# CrossOver indicator
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)

    def next(self):
        if self.crossover > 0:  # Fast crossed above slow
            self.buy()
        elif self.crossover < 0:  # Fast crossed below slow
            self.sell()

```bash

## Indicator Parameters

```python

# Using strategy params for indicators

class MyStrategy(bt.Strategy):
    params = (
        ('ma_period', 20),
        ('rsi_period', 14),
    )

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.ma_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

```bash

## Indicator on Indicator

Indicators can be calculated on other indicators.

```python
class MyStrategy(bt.Strategy):
    def __init__(self):

# SMA of SMA (smoothed moving average)
        self.sma = bt.indicators.SMA(self.data.close, period=10)
        self.sma_sma = bt.indicators.SMA(self.sma, period=5)

# RSI of closing price
        self.rsi = bt.indicators.RSI(self.data.close, period=14)

# SMA of RSI (RSI smoothing)
        self.rsi_sma = bt.indicators.SMA(self.rsi, period=5)

```bash

## Accessing Indicator Lines

Some indicators have multiple output lines.

```python

# MACD has multiple lines

macd = bt.indicators.MACD(self.data.close)

# Access individual lines

macd_line = macd.macd[0]        # MACD line

signal_line = macd.signal[0]    # Signal line

histogram = macd.histo[0]      # Histogram

# Bollinger Bands

bollinger = bt.indicators.BollingerBands(self.data.close)

mid = bollinger.mid[0]          # Middle band (SMA)

top = bollinger.top[0]          # Upper band

bot = bollinger.bot[0]          # Lower band

```bash

## Plotting Indicators

```python
class MyStrategy(bt.Strategy):
    def __init__(self):

# Indicators are automatically plotted
        self.sma = bt.indicators.SMA(self.data.close, period=20)

# To disable plotting
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.rsi.plotinfo.plot = False  # Don't plot RSI

```bash

## Available Indicators Reference

| Indicator | Description | Parameters |

|-----------|-------------|------------|

| SMA | Simple Moving Average | period |

| EMA | Exponential Moving Average | period |

| WMA | Weighted Moving Average | period |

| RSI | Relative Strength Index | period, upper, lower |

| MACD | MACD | period_me1, period_me2, signal |

| BollingerBands | Bollinger Bands | period, devfactor |

| ATR | Average True Range | period |

| Stochastic | Stochastic Oscillator | period, period_dfast, period_dslow |

| CCI | Commodity Channel Index | period, upper, lower |

| ADX | Average Directional Index | period |

| Aroon | Aroon Indicator | period |

| CrossOver | Crossover detection | period |

| Oscillator | Oscillator (fast-slow) | p1, p2 |

## Next Steps

- [Strategies](strategies.md) - Use indicators in strategies
- [Analyzers](analyzers.md) - Analyze strategy performance
