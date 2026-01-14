========
Strategy
========

The ``Strategy`` class is the base class for all trading strategies.

.. automodule:: backtrader.strategy
   :members:
   :undoc-members:
   :show-inheritance:
   :special-members: __init__
   :no-index:

Overview
--------

A Strategy is where trading logic is implemented. It has access to:

- Data feeds (OHLCV data)
- Indicators
- Broker (for order execution)
- Portfolio information (cash, positions)

Lifecycle Methods
-----------------

- ``__init__()``: Initialize indicators and variables
- ``prenext()``: Called before minimum period is reached
- ``nextstart()``: Called once when minimum period is first reached
- ``next()``: Called for each bar after minimum period
- ``start()``: Called at the start of backtesting
- ``stop()``: Called at the end of backtesting

Notification Methods
--------------------

- ``notify_order()``: Called when order status changes
- ``notify_trade()``: Called when trade is opened/closed
- ``notify_cashvalue()``: Called with cash and portfolio value updates

Order Methods
-------------

- ``buy()``: Create a buy order
- ``sell()``: Create a sell order
- ``close()``: Close a position
- ``cancel()``: Cancel an order

Example
-------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       params = (
           ('period', 20),
           ('stake', 10),
       )
       
       def __init__(self):
           self.sma = bt.indicators.SMA(
               self.data.close, 
               period=self.params.period
           )
           self.order = None
       
       def notify_order(self, order):
           if order.status in [order.Completed]:
               if order.isbuy():
                   print(f'BUY EXECUTED @ {order.executed.price}')
               else:
                   print(f'SELL EXECUTED @ {order.executed.price}')
           self.order = None
       
       def next(self):
           if self.order:
               return
               
           if not self.position:
               if self.data.close[0] > self.sma[0]:
                   self.order = self.buy(size=self.params.stake)
           else:
               if self.data.close[0] < self.sma[0]:
                   self.order = self.sell(size=self.params.stake)
