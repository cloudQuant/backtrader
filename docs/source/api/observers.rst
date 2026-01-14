=========
Observers
=========

Observers track and visualize trading activity.

.. automodule:: backtrader.observers
   :members:
   :undoc-members:
   :show-inheritance:
   :no-index:

Overview
--------

Observers are special indicators that track the state of the trading system.
They are used for visualization and do not affect trading logic.

Built-in Observers
------------------

- ``Broker``: Cash and portfolio value
- ``BuySell``: Buy/sell markers on chart
- ``Trades``: Trade markers and P&L
- ``DrawDown``: Drawdown visualization
- ``TimeReturn``: Period returns
- ``Benchmark``: Compare against benchmark

Using Observers
---------------

.. code-block:: python

   cerebro = bt.Cerebro(stdstats=False)  # Disable default observers
   
   # Add specific observers
   cerebro.addobserver(bt.observers.Broker)
   cerebro.addobserver(bt.observers.BuySell)
   cerebro.addobserver(bt.observers.Trades)
   cerebro.addobserver(bt.observers.DrawDown)
   
   # Run and plot
   cerebro.run()
   cerebro.plot()

Benchmark Observer
------------------

.. code-block:: python

   # Add benchmark data
   benchmark = bt.feeds.YahooFinanceCSVData(dataname='SPY.csv')
   cerebro.adddata(benchmark, name='benchmark')
   
   # Add benchmark observer
   cerebro.addobserver(
       bt.observers.Benchmark,
       data=benchmark,
       timeframe=bt.TimeFrame.NoTimeFrame
   )

Creating Custom Observers
-------------------------

.. code-block:: python

   class MyObserver(bt.Observer):
       lines = ('custom',)
       plotinfo = dict(plot=True, subplot=True)
       
       def next(self):
           # Track custom metric
           self.lines.custom[0] = self._owner.broker.getvalue()
