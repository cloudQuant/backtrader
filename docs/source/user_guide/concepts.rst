=============
Core Concepts
=============

This chapter explains the fundamental concepts of Backtrader. Understanding these
concepts is essential for effective strategy development.

.. tip::
   For more detailed explanations, see the `Author's Blog <https://yunjinqi.blog.csdn.net/>`_.

Understanding Lines
-------------------

**Lines** are the fundamental data structure in Backtrader, similar to columns in
an Excel spreadsheet. Each Line represents a time series where each point corresponds
to a specific time (bar).

Think of it like Excel:

- A **class** (Strategy, Indicator) is like a **workbook**
- Each **Line** is like a **column** in the workbook
- Each **bar** is like a **row** in the column

.. code-block:: python

   # Access current bar value (index 0)
   current_close = self.data.close[0]
   
   # Access previous bar value (index -1)
   previous_close = self.data.close[-1]
   
   # Access 5 bars ago
   close_5_bars_ago = self.data.close[-5]
   
   # Get multiple values as array
   last_10_closes = self.data.close.get(size=10)

.. note::
   Index ``[0]`` is the current bar, negative indices look back in time.
   Positive indices ``[1]``, ``[2]`` look forward (only valid in indicators during ``__init__``).

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

Strategy Lifecycle
------------------

Backtrader uses an event-driven model. The author compares it to human life stages:

.. list-table::
   :widths: 20 20 60
   :header-rows: 1

   * - Method
     - Life Stage
     - Description
   * - ``__init__``
     - Conception
     - Initialize indicators and variables
   * - ``start``
     - Birth
     - Called once at beginning, usually empty
   * - ``prenext``
     - Childhood
     - Called before indicators have enough data
   * - ``nextstart``
     - Coming of Age
     - Called once when minimum period is reached
   * - ``next``
     - Adulthood
     - Main trading logic, called for each bar
   * - ``stop``
     - Death
     - Called at end, output results here

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def __init__(self):
           '''Initialize indicators and variables'''
           self.sma = bt.indicators.SMA(period=20)
           self.order = None
       
       def start(self):
           '''Called once at beginning'''
           self.log('Strategy starting')
       
       def prenext(self):
           '''Called before indicators have enough data.
           Useful for debugging or early logic.'''
           pass
       
       def nextstart(self):
           '''Called once when minimum period is reached'''
           self.next()  # Often just calls next()
       
       def next(self):
           '''Main trading logic - called for each bar'''
           if self.data.close[0] > self.sma[0]:
               self.buy()
       
       def stop(self):
           '''Called at end - output results'''
           self.log(f'Final Value: {self.broker.getvalue():.2f}')

Notification Events
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   def notify_order(self, order):
       '''Called when order status changes'''
       if order.status == order.Submitted:
           return  # Order submitted to broker
       if order.status == order.Accepted:
           return  # Order accepted by broker
       if order.status == order.Completed:
           if order.isbuy():
               self.log(f'BUY @ {order.executed.price:.2f}')
           else:
               self.log(f'SELL @ {order.executed.price:.2f}')
       elif order.status == order.Canceled:
           self.log('Order canceled')
       elif order.status == order.Margin:
           self.log('Insufficient margin')
       elif order.status == order.Rejected:
           self.log('Order rejected')
   
   def notify_trade(self, trade):
       '''Called when trade is opened or closed'''
       if trade.isclosed:
           self.log(f'TRADE CLOSED - PnL: {trade.pnl:.2f}, Net: {trade.pnlcomm:.2f}')
       if trade.isopen:
           self.log(f'TRADE OPENED @ {trade.price:.2f}')
   
   def notify_cashvalue(self, cash, value):
       '''Called when cash or value changes'''
       pass  # Rarely used

Cerebro - The Brain
-------------------

Cerebro is the central engine that orchestrates everything:

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # 1. Add data
   data = bt.feeds.GenericCSVData(dataname='data.csv')
   cerebro.adddata(data, name='AAPL')
   
   # 2. Add strategy with parameters
   cerebro.addstrategy(MyStrategy, period=20, stake=100)
   
   # 3. Add analyzers
   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
   
   # 4. Add observers (for plotting)
   cerebro.addobserver(bt.observers.Broker)
   cerebro.addobserver(bt.observers.Trades)
   cerebro.addobserver(bt.observers.BuySell)
   
   # 5. Set broker parameters
   cerebro.broker.setcash(100000)
   cerebro.broker.setcommission(commission=0.001)
   
   # 6. Run
   results = cerebro.run()
   
   # 7. Get results
   strat = results[0]
   print(f"Sharpe: {strat.analyzers.sharpe.get_analysis()}")
   
   # 8. Plot
   cerebro.plot()

Key Cerebro Parameters
~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 20 15 65
   :header-rows: 1

   * - Parameter
     - Default
     - Description
   * - preload
     - True
     - Pre-load data into memory (faster backtesting)
   * - runonce
     - True
     - Calculate indicators vectorized (faster)
   * - live
     - False
     - Live trading mode (disables preload and runonce)
   * - maxcpus
     - None
     - CPUs for optimization (None = all)
   * - stdstats
     - True
     - Add default observers (Broker, Trades, BuySell)

See Also
--------

- :doc:`strategies` - Strategy development
- :doc:`data_feeds` - Data loading
- :doc:`indicators` - Technical indicators
