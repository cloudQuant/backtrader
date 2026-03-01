============
Live Trading
============

Backtrader supports live trading through integrations with various brokers and
exchanges. This guide covers setup and best practices for transitioning from
backtesting to live trading.

Supported Brokers
-----------------

.. list-table::
   :widths: 25 25 50
   :header-rows: 1

   * - Broker
     - Markets
     - Description
   * - Interactive Brokers
     - Stocks, Futures, Options, Forex
     - Professional multi-asset broker
   * - CCXT
     - Cryptocurrencies
     - 100+ crypto exchanges
   * - Alpaca
     - US Stocks
     - Commission-free trading
   * - OANDA
     - Forex
     - Forex trading platform

Interactive Brokers Integration
-------------------------------

Prerequisites
^^^^^^^^^^^^^

1. Install IB Gateway or TWS (Trader Workstation)
2. Enable API connections in IB settings
3. Install ``ib_insync`` package

.. code-block:: bash

   pip install ib_insync

Configuration
^^^^^^^^^^^^^

.. code-block:: python

   import backtrader as bt
   from backtrader.stores import IBStore
   
   # Create IB store
   ibstore = IBStore(
       host='127.0.0.1',
       port=7497,           # 7497 for TWS paper, 7496 for live
       clientId=1,
       notifyall=False,
       _debug=False
   )
   
   cerebro = bt.Cerebro()
   
   # Set IB as broker
   cerebro.setbroker(ibstore.getbroker())

Live Data Feed
^^^^^^^^^^^^^^

.. code-block:: python

   from backtrader.feeds import IBData
   
   # Stock data
   data = IBData(
       dataname='AAPL',
       sectype='STK',
       exchange='SMART',
       currency='USD',
       historical=True,
       what='TRADES',
       useRTH=True,
       qcheck=0.5,
       backfill_start=True,
       backfill=True,
       latethrough=False
   )
   
   cerebro.adddata(data)

Futures Data
^^^^^^^^^^^^

.. code-block:: python

   # E-mini S&P 500 futures
   data = IBData(
       dataname='ES',
       sectype='FUT',
       exchange='CME',
       currency='USD',
       expiry='202403'
   )

Live Strategy Example
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   class IBLiveStrategy(bt.Strategy):
       params = (('period', 20),)
       
       def __init__(self):
           self.sma = bt.indicators.SMA(period=self.params.period)
           self.order = None
       
       def log(self, txt, dt=None):
           dt = dt or self.data.datetime.datetime(0)
           print(f'{dt.isoformat()} {txt}')
       
       def notify_order(self, order):
           if order.status in [order.Submitted, order.Accepted]:
               return
           
           if order.status == order.Completed:
               if order.isbuy():
                   self.log(f'BUY EXECUTED @ {order.executed.price:.2f}')
               else:
                   self.log(f'SELL EXECUTED @ {order.executed.price:.2f}')
           
           self.order = None
       
       def next(self):
           if self.order:
               return
           
           if not self.position:
               if self.data.close[0] > self.sma[0]:
                   self.order = self.buy()
           else:
               if self.data.close[0] < self.sma[0]:
                   self.order = self.close()

CCXT Cryptocurrency Integration
-------------------------------

Setup
^^^^^

.. code-block:: bash

   pip install ccxt

Configuration
^^^^^^^^^^^^^

.. code-block:: python

   import backtrader as bt
   from backtrader.stores import CCXTStore
   
   # Create CCXT store for Binance
   config = {
       'apiKey': 'your_api_key',
       'secret': 'your_secret',
       'enableRateLimit': True,
   }
   
   store = CCXTStore(
       exchange='binance',
       currency='USDT',
       config=config,
       retries=5,
       sandbox=True  # Use sandbox for testing
   )
   
   cerebro = bt.Cerebro()
   cerebro.setbroker(store.getbroker())

Crypto Data Feed
^^^^^^^^^^^^^^^^

.. code-block:: python

   from backtrader.feeds import CCXTFeed
   
   # BTC/USDT 1-hour bars
   data = CCXTFeed(
       exchange='binance',
       symbol='BTC/USDT',
       timeframe=bt.TimeFrame.Minutes,
       compression=60,
       config=config,
       retries=5,
       historical=True,
       backfill=True
   )
   
   cerebro.adddata(data)

Multi-Timeframe with Resampling
-------------------------------

When using live data with multiple timeframes:

.. code-block:: python

   # Base data (1 minute)
   data0 = IBData(
       dataname='AAPL',
       sectype='STK',
       exchange='SMART',
       currency='USD',
       timeframe=bt.TimeFrame.Minutes,
       compression=1
   )
   cerebro.adddata(data0)
   
   # Resample to 5 minutes
   cerebro.resampledata(
       data0,
       timeframe=bt.TimeFrame.Minutes,
       compression=5
   )
   
   # Resample to 1 hour
   cerebro.resampledata(
       data0,
       timeframe=bt.TimeFrame.Minutes,
       compression=60
   )

.. warning::
   When using resampled data in live trading, be aware of the timing issues.
   The resampled bar is only complete when the next bar of the base timeframe arrives.

Paper Trading
-------------

Always test strategies with paper trading before going live:

Interactive Brokers Paper
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # Use paper trading port
   ibstore = IBStore(
       host='127.0.0.1',
       port=7497,  # Paper trading port
       clientId=1
   )

CCXT Sandbox
^^^^^^^^^^^^

.. code-block:: python

   store = CCXTStore(
       exchange='binance',
       currency='USDT',
       config=config,
       sandbox=True  # Enable sandbox mode
   )

Risk Management for Live Trading
---------------------------------

Position Limits
^^^^^^^^^^^^^^^

.. code-block:: python

   class SafeStrategy(bt.Strategy):
       params = (
           ('max_position_pct', 0.1),  # Max 10% per position
           ('max_daily_trades', 10),
       )
       
       def __init__(self):
           self.daily_trades = 0
           self.last_trade_date = None
       
       def next(self):
           # Reset daily counter
           current_date = self.data.datetime.date(0)
           if current_date != self.last_trade_date:
               self.daily_trades = 0
               self.last_trade_date = current_date
           
           # Check limits
           if self.daily_trades >= self.p.max_daily_trades:
               return
           
           # Calculate position size
           max_value = self.broker.getvalue() * self.p.max_position_pct
           size = int(max_value / self.data.close[0])
           
           if size > 0 and not self.position:
               self.buy(size=size)
               self.daily_trades += 1

Emergency Stop
^^^^^^^^^^^^^^

.. code-block:: python

   class EmergencyStopStrategy(bt.Strategy):
       params = (('max_drawdown_pct', 0.05),)  # 5% max drawdown
       
       def __init__(self):
           self.initial_value = None
           self.emergency_stop = False
       
       def start(self):
           self.initial_value = self.broker.getvalue()
       
       def next(self):
           if self.emergency_stop:
               return
           
           # Check drawdown
           current_value = self.broker.getvalue()
           drawdown = (self.initial_value - current_value) / self.initial_value
           
           if drawdown >= self.p.max_drawdown_pct:
               self.log('EMERGENCY STOP - Max drawdown reached')
               self.close()  # Close all positions
               self.emergency_stop = True

Logging and Monitoring
----------------------

.. code-block:: python

   import logging
   
   # Setup logging
   logging.basicConfig(
       level=logging.INFO,
       format='%(asctime)s - %(levelname)s - %(message)s',
       handlers=[
           logging.FileHandler('trading.log'),
           logging.StreamHandler()
       ]
   )
   
   class LoggedStrategy(bt.Strategy):
       def log(self, txt, level=logging.INFO):
           dt = self.data.datetime.datetime(0)
           logging.log(level, f'{dt} - {txt}')
       
       def notify_order(self, order):
           if order.status == order.Completed:
               self.log(f'Order completed: {order.executed.price}')
           elif order.status in [order.Canceled, order.Rejected]:
               self.log(f'Order failed: {order.status}', logging.WARNING)

Best Practices
--------------

1. **Start with Paper Trading**: Always test on paper/sandbox first
2. **Implement Logging**: Log all orders and trades for review
3. **Set Position Limits**: Never risk more than you can afford to lose
4. **Handle Disconnections**: Implement reconnection logic
5. **Monitor Slippage**: Compare expected vs actual execution prices
6. **Use Stop Losses**: Always have exit conditions
7. **Test During Market Hours**: Paper trade during actual market hours

Common Issues
-------------

Connection Problems
^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # Reconnection handling
   def notify_store(self, msg, *args, **kwargs):
       if 'connection' in msg.lower():
           self.log(f'Store notification: {msg}')
           # Implement reconnection logic

Data Gaps
^^^^^^^^^

.. code-block:: python

   def next(self):
       # Check for data gaps
       if len(self) > 1:
           time_diff = self.data.datetime[0] - self.data.datetime[-1]
           if time_diff > expected_interval * 2:
               self.log('Warning: Data gap detected')

See Also
--------

- :doc:`brokers` - Broker configuration
- :doc:`strategies` - Strategy development
- :doc:`performance` - Performance optimization
