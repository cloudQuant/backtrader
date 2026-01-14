========
Cerebro
========

The ``Cerebro`` class is the main engine of the Backtrader framework.

.. automodule:: backtrader.cerebro
   :members:
   :undoc-members:
   :show-inheritance:
   :special-members: __init__
   :no-index:

Overview
--------

Cerebro is the central orchestrator for backtesting and live trading operations. 
It manages:

- Data feed synchronization
- Strategy instantiation and execution
- Broker integration for order execution
- Multi-core optimization support
- Live trading and backtesting modes
- Plotting and analysis capabilities

Basic Usage
-----------

.. code-block:: python

   import backtrader as bt

   cerebro = bt.Cerebro()
   
   # Add data
   data = bt.feeds.GenericCSVData(dataname='data.csv')
   cerebro.adddata(data)
   
   # Add strategy
   cerebro.addstrategy(MyStrategy)
   
   # Set broker parameters
   cerebro.broker.setcash(100000)
   cerebro.broker.setcommission(commission=0.001)
   
   # Run backtest
   results = cerebro.run()
   
   # Plot results
   cerebro.plot()

Key Parameters
--------------

- ``preload``: Whether to preload data feeds (default: True)
- ``runonce``: Run indicators in vectorized mode (default: True)
- ``live``: Enable live trading mode (default: False)
- ``maxcpus``: Maximum CPUs for optimization (default: None)
- ``stdstats``: Add standard observers (default: True)
- ``exactbars``: Memory optimization level (default: False)

Methods
-------

Adding Components
~~~~~~~~~~~~~~~~~

- ``adddata()``: Add a data feed
- ``addstrategy()``: Add a strategy class
- ``addanalyzer()``: Add an analyzer
- ``addobserver()``: Add an observer
- ``addsizer()``: Add a position sizer

Execution
~~~~~~~~~

- ``run()``: Execute the backtest/trading
- ``plot()``: Generate charts

Configuration
~~~~~~~~~~~~~

- ``broker``: Access the broker instance
- ``setbroker()``: Set a custom broker
