========================
Backtrader API Reference
========================

This section contains complete API documentation for the Backtrader framework,
automatically generated from source code docstrings.

.. contents:: Table of Contents
   :local:
   :depth: 2

Core Package
============

.. toctree::
   :maxdepth: 4

   backtrader

Quick Reference
===============

Core Classes
------------

The main classes you'll work with in Backtrader:

- :class:`backtrader.Cerebro` - The main engine that orchestrates everything
- :class:`backtrader.Strategy` - Base class for trading strategies
- :class:`backtrader.Indicator` - Base class for technical indicators
- :class:`backtrader.Analyzer` - Base class for performance analyzers
- :class:`backtrader.Observer` - Base class for observers
- :class:`backtrader.Sizer` - Base class for position sizers
- :class:`backtrader.Order` - Order representation
- :class:`backtrader.Trade` - Trade representation
- :class:`backtrader.Position` - Position tracking

Data Feeds
----------

Available data feed classes for loading market data:

- :class:`backtrader.feeds.GenericCSVData` - Flexible CSV data loader
- :class:`backtrader.feeds.PandasData` - Load from pandas DataFrame
- :class:`backtrader.feeds.YahooFinanceCSVData` - Yahoo Finance format
- :class:`backtrader.feeds.BacktraderCSVData` - Native Backtrader format

Technical Indicators
--------------------

Backtrader includes 50+ built-in indicators:

**Moving Averages:**
SMA, EMA, WMA, SMMA, DEMA, KAMA, HMA, ZLEMA

**Oscillators:**
RSI, Stochastic, MACD, CCI, Williams %R, Ultimate Oscillator

**Volatility:**
ATR, Bollinger Bands, Standard Deviation

**Trend:**
ADX, Aroon, Parabolic SAR, Ichimoku, DPO

**Momentum:**
ROC, Momentum, KST, TSI, TRIX

See :doc:`backtrader.indicators` for complete list.

Performance Analyzers
---------------------

Built-in analyzers for strategy evaluation:

- :class:`backtrader.analyzers.SharpeRatio` - Sharpe ratio calculation
- :class:`backtrader.analyzers.DrawDown` - Drawdown analysis
- :class:`backtrader.analyzers.TradeAnalyzer` - Trade statistics
- :class:`backtrader.analyzers.Returns` - Return metrics
- :class:`backtrader.analyzers.SQN` - System Quality Number
- :class:`backtrader.analyzers.VWR` - Variability-Weighted Return

See :doc:`backtrader.analyzers` for complete list.

Position Sizers
---------------

Built-in sizers for position sizing:

- :class:`backtrader.sizers.FixedSize` - Fixed number of units
- :class:`backtrader.sizers.PercentSizer` - Percentage of portfolio
- :class:`backtrader.sizers.AllInSizer` - Use all available cash

See :doc:`backtrader.sizers` for complete list
