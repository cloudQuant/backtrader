==========
Strategies
==========

Strategy Structure
------------------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       params = (
           ('period', 20),
           ('stake', 10),
       )
       
       def __init__(self):
           # Initialize indicators
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
           # Trading logic
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
