=============
Core Concepts
=============

Understanding Lines
-------------------

**Lines** are the fundamental data structure in Backtrader. They represent
time series data where each point corresponds to a specific time (bar).

.. code-block:: python

   # Access current bar value
   current_close = self.data.close[0]
   
   # Access previous bar value
   previous_close = self.data.close[-1]
   
   # Access 5 bars ago
   close_5_bars_ago = self.data.close[-5]

.. note::
   Index ``[0]`` is the current bar, negative indices look back in time.

Data Feeds
----------

Data feeds provide OHLCV data:

- **Open**: Opening price
- **High**: Highest price
- **Low**: Lowest price
- **Close**: Closing price
- **Volume**: Trading volume
- **OpenInterest**: Open interest (futures)

.. code-block:: python

   # Access data lines
   self.data.open[0]
   self.data.high[0]
   self.data.low[0]
   self.data.close[0]
   self.data.volume[0]
   self.data.datetime[0]  # Float representation

Timeframes
----------

Supported timeframes:

- ``TimeFrame.Ticks``
- ``TimeFrame.Seconds``
- ``TimeFrame.Minutes``
- ``TimeFrame.Days``
- ``TimeFrame.Weeks``
- ``TimeFrame.Months``
- ``TimeFrame.Years``

Indicators
----------

Indicators calculate values from data:

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def __init__(self):
           # Indicator automatically calculates for each bar
           self.sma = bt.indicators.SMA(self.data.close, period=20)
       
       def next(self):
           # Use indicator value
           if self.data.close[0] > self.sma[0]:
               self.buy()

Orders
------

Order types:

- **Market**: Execute at current price
- **Limit**: Execute at specified price or better
- **Stop**: Execute when price reaches trigger
- **StopLimit**: Combination of stop and limit

.. code-block:: python

   # Market order
   self.buy()
   
   # Limit order
   self.buy(exectype=bt.Order.Limit, price=100.0)
   
   # Stop order
   self.buy(exectype=bt.Order.Stop, price=105.0)
   
   # Stop-limit order
   self.buy(exectype=bt.Order.StopLimit, price=105.0, plimit=106.0)

Positions
---------

A position represents holdings in an asset:

.. code-block:: python

   # Check if we have a position
   if self.position:
       print(f'Size: {self.position.size}')
       print(f'Price: {self.position.price}')
   
   # Check position for specific data
   pos = self.getposition(self.data)

Event-Driven Model
------------------

Backtrader uses an event-driven model:

1. ``start()``: Called at beginning
2. ``prenext()``: Called before minimum period
3. ``nextstart()``: Called once at minimum period
4. ``next()``: Called for each subsequent bar
5. ``stop()``: Called at end

Notification events:

- ``notify_order(order)``: Order status change
- ``notify_trade(trade)``: Trade update
- ``notify_cashvalue(cash, value)``: Portfolio update
