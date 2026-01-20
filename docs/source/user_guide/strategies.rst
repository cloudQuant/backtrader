==========
Strategies
==========

Strategies contain your trading logic. They receive market data, calculate indicators,
and generate trading signals.

Strategy Lifecycle
------------------

Understand the strategy lifecycle (like human life stages):

.. list-table::
   :widths: 20 20 60
   :header-rows: 1

   * - Method
     - Stage
     - Description
   * - ``__init__``
     - Birth
     - Initialize indicators and variables. Called once at start.
   * - ``start``
     - Ready
     - Called once before processing begins. Usually empty.
   * - ``prenext``
     - Childhood
     - Called when minimum period not yet satisfied (indicators warming up).
   * - ``nextstart``
     - Adulthood begins
     - Called once when transitioning from prenext to next.
   * - ``next``
     - Adulthood
     - Main trading logic. Called for each bar after minimum period.
   * - ``stop``
     - End
     - Called once after all data processed. Good for final reporting.

.. warning::
   With **multiple data feeds** that have different start dates, ``next`` won't be
   called until ALL data feeds have valid bars. Use ``prenext`` to call ``self.next()``
   manually if needed, but filter out data that hasn't started yet.

Strategy Structure
------------------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       params = (
           ('period', 20),
           ('stake', 10),
       )
       
       def __init__(self):
           # Initialize indicators (vectorized calculation)
           self.sma = bt.indicators.SMA(period=self.p.period)
           self.order = None
       
       def notify_order(self, order):
           # Handle order notifications
           if order.status in [order.Completed]:
               if order.isbuy():
                   self.log(f'BUY @ {order.executed.price:.2f}')
               else:
                   self.log(f'SELL @ {order.executed.price:.2f}')
           self.order = None
       
       def next(self):
           # Trading logic - called for each bar
           if self.order:
               return
           
           if not self.position:
               if self.data.close[0] > self.sma[0]:
                   self.order = self.buy(size=self.p.stake)
           else:
               if self.data.close[0] < self.sma[0]:
                   self.order = self.sell(size=self.p.stake)
       
       def log(self, txt):
           dt = self.datas[0].datetime.date(0)
           print(f'{dt} {txt}')

Parameters
----------

Define and use parameters:

.. code-block:: python

   class MyStrategy(bt.Strategy):
       params = (
           ('fast', 10),
           ('slow', 30),
           ('risk', 0.02),
       )
       
       def __init__(self):
           # Access parameters
           print(f'Fast: {self.p.fast}')
           print(f'Slow: {self.params.slow}')
   
   # Override when adding
   cerebro.addstrategy(MyStrategy, fast=5, slow=20)

Order Management
----------------

.. code-block:: python

   def next(self):
       # Simple buy/sell
       self.buy()
       self.sell()
       
       # With size
       self.buy(size=100)
       
       # Limit order
       self.buy(exectype=bt.Order.Limit, price=99.0, size=100)
       
       # Stop loss
       self.sell(exectype=bt.Order.Stop, price=95.0)
       
       # Bracket order (entry + stop + target)
       self.buy_bracket(
           size=100,
           price=100.0,
           stopprice=95.0,
           limitprice=110.0
       )
       
       # Close position
       self.close()
       
       # Cancel order
       self.cancel(self.order)

Multiple Data Feeds
-------------------

.. code-block:: python

   class MultiDataStrategy(bt.Strategy):
       def __init__(self):
           # Indicators for each data
           self.sma0 = bt.indicators.SMA(self.data0.close)
           self.sma1 = bt.indicators.SMA(self.data1.close)
       
       def next(self):
           # Trade different instruments
           if self.data0.close[0] > self.sma0[0]:
               self.buy(data=self.data0)
           
           if self.data1.close[0] < self.sma1[0]:
               self.sell(data=self.data1)

Position Sizing
---------------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def next(self):
           # Calculate size based on risk
           risk_per_trade = self.broker.getvalue() * 0.02
           atr = self.atr[0]
           size = int(risk_per_trade / atr)
           
           self.buy(size=size)

Logging and Debugging
---------------------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def log(self, txt, dt=None):
           dt = dt or self.datas[0].datetime.date(0)
           print(f'{dt.isoformat()} {txt}')
       
       def next(self):
           self.log(f'Close: {self.data.close[0]:.2f}')
           self.log(f'Position: {self.position.size}')
           self.log(f'Cash: {self.broker.getcash():.2f}')

Handling Multi-Data with prenext
--------------------------------

When data feeds have different start dates:

.. code-block:: python

   class MultiDataStrategy(bt.Strategy):
       def prenext(self):
           # Force entry into next even during warmup
           self.next()
       
       def next(self):
           for data in self.datas:
               # Check if this data has started
               if len(data) == 0:
                   continue
               
               # Check if data is current (not historical)
               if data.datetime.date(0) != self.data.datetime.date(0):
                   continue
               
               # Now safe to use this data
               self.process_data(data)

Notification Methods
--------------------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def notify_order(self, order):
           '''Called when order status changes'''
           if order.status == order.Completed:
               print(f'Order {order.ref} completed at {order.executed.price}')
           elif order.status == order.Canceled:
               print(f'Order {order.ref} canceled')
           elif order.status == order.Rejected:
               print(f'Order {order.ref} rejected')
       
       def notify_trade(self, trade):
           '''Called when trade status changes'''
           if trade.isclosed:
               print(f'Trade PnL: Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}')
       
       def notify_cashvalue(self, cash, value):
           '''Called when cash/value changes'''
           print(f'Cash: {cash:.2f}, Value: {value:.2f}')

Best Practices
--------------

1. **Declare indicators in __init__**: Enables vectorized calculation
2. **Track pending orders**: Prevent duplicate orders
3. **Use notify_order**: Handle order status properly
4. **Filter multi-data**: Check data validity in prenext/next
5. **Log key events**: Aids debugging and analysis

See Also
--------

- :doc:`concepts` - Strategy lifecycle details
- :doc:`indicators` - Using indicators
- :doc:`brokers` - Order management
- `Blog: Strategy讲解 <https://yunjinqi.blog.csdn.net/article/details/108569865>`_
- `Blog: prenext与next区别 <https://yunjinqi.blog.csdn.net/article/details/126337204>`_
