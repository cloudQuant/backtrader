==========================
Frequently Asked Questions
==========================

This section covers common questions and solutions when using Backtrader.

Installation & Setup
--------------------

Q: How do I install Backtrader?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   # Clone from GitHub
   git clone https://github.com/cloudQuant/backtrader.git
   cd backtrader
   pip install -r requirements.txt
   pip install -e .
   
   # Or clone from Gitee (recommended for users in China)
   git clone https://gitee.com/yunjinqi/backtrader.git

Q: Which Python version should I use?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Python 3.9+ is required. Python 3.11+ is recommended for ~15% performance improvement.

Q: Backtrader won't install on my system
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Common solutions:

.. code-block:: bash

   # Update pip
   pip install --upgrade pip
   
   # Install with user flag
   pip install -e . --user
   
   # Use a virtual environment
   python -m venv bt_env
   source bt_env/bin/activate  # Linux/Mac
   bt_env\Scripts\activate     # Windows
   pip install -e .

Data Issues
-----------

Q: My CSV data won't load correctly
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Check the date format and column order:

.. code-block:: python

   data = bt.feeds.GenericCSVData(
       dataname='data.csv',
       datetime=0,      # Date/time column index
       open=1,
       high=2,
       low=3,
       close=4,
       volume=5,
       openinterest=-1, # -1 means not present
       dtformat='%Y-%m-%d',  # Date format
       tmformat='%H:%M:%S',  # Time format (if needed)
   )

Q: How do I use a Pandas DataFrame as a data source?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   import pandas as pd
   import backtrader as bt
   
   df = pd.read_csv('data.csv', parse_dates=['date'], index_col='date')
   data = bt.feeds.PandasData(dataname=df)
   cerebro.adddata(data)

Q: How do I handle missing data?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # Fill missing values in pandas before loading
   df = df.fillna(method='ffill')  # Forward fill
   
   # Or drop missing rows
   df = df.dropna()

Strategy Issues
---------------

Q: My strategy isn't executing any trades
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Common causes:

1. **Insufficient capital**: Check ``cerebro.broker.setcash()``
2. **Indicator warm-up period**: Not enough data for indicator calculation
3. **Logic error**: Check buy/sell conditions

.. code-block:: python

   def next(self):
       # Debug output
       print(f'Date: {self.data.datetime.date(0)}')
       print(f'Close: {self.data.close[0]}')
       print(f'SMA: {self.sma[0]}')
       print(f'Position: {self.position.size}')
       
       if not self.position:
           if self.data.close[0] > self.sma[0]:
               print('Buy signal')
               self.buy()

Q: Why is prenext() called instead of next()?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``prenext()`` is called before all indicators have enough data. Check your longest indicator period.

.. code-block:: python

   def __init__(self):
       self.sma50 = bt.indicators.SMA(period=50)  # Needs 50 bars
   
   def prenext(self):
       # Called for the first 49 bars
       pass
   
   def next(self):
       # Called from bar 50 onwards
       pass

Q: How do I trade multiple instruments?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   cerebro.adddata(data1, name='AAPL')
   cerebro.adddata(data2, name='GOOGL')
   
   class MultiStrategy(bt.Strategy):
       def next(self):
           for i, data in enumerate(self.datas):
               if not self.getposition(data):
                   if data.close[0] > data.close[-1]:
                       self.buy(data=data)

Orders & Broker Issues
----------------------

Q: How do I set commission and slippage?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # Commission (0.1%)
   cerebro.broker.setcommission(commission=0.001)
   
   # Fixed slippage
   cerebro.broker.set_slippage_fixed(fixed=0.01)
   
   # Percentage slippage
   cerebro.broker.set_slippage_perc(perc=0.0005)

Q: Why is my order rejected?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Check if you have sufficient funds or margin:

.. code-block:: python

   def notify_order(self, order):
       if order.status == order.Rejected:
           print(f'Order rejected - Cash: {self.broker.getcash()}')
       elif order.status == order.Margin:
           print('Insufficient margin')

Q: How do I implement stop-loss and take-profit?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # Method 1: Bracket orders
   self.buy_bracket(
       price=100.0,
       stopprice=95.0,   # Stop-loss
       limitprice=110.0  # Take-profit
   )
   
   # Method 2: Manual tracking
   def __init__(self):
       self.entry_price = None
   
   def next(self):
       if self.position and self.entry_price:
           pnl_pct = (self.data.close[0] - self.entry_price) / self.entry_price
           if pnl_pct < -0.05:  # -5% stop-loss
               self.close()
           elif pnl_pct > 0.10:  # +10% take-profit
               self.close()

Indicator Issues
----------------

Q: How do I access indicator values from previous bars?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # Current bar
   current_sma = self.sma[0]
   
   # Previous bar
   prev_sma = self.sma[-1]
   
   # 5 bars ago
   old_sma = self.sma[-5]

Q: How do I create a custom indicator?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   class MyIndicator(bt.Indicator):
       lines = ('myline',)
       params = (('period', 20),)
       
       def __init__(self):
           self.addminperiod(self.p.period)
       
       def next(self):
           self.lines.myline[0] = sum(self.data.get(size=self.p.period)) / self.p.period

Performance Issues
------------------

Q: Backtesting is too slow
^^^^^^^^^^^^^^^^^^^^^^^^^^^

See :doc:`../visualization/plotting` for the full optimization guide. Quick tips:

.. code-block:: python

   # 1. Use vectorized mode
   cerebro.run(runonce=True)  # Default
   
   # 2. Use Python 3.11+
   
   # 3. Use pickle instead of CSV
   df.to_pickle('data.pkl')
   df = pd.read_pickle('data.pkl')
   
   # 4. Limit data range
   data = bt.feeds.GenericCSVData(
       dataname='data.csv',
       fromdate=datetime(2020, 1, 1),
       todate=datetime(2023, 12, 31)
   )

Q: How do I use multiple CPUs for optimization?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   cerebro.optstrategy(
       MyStrategy,
       period=range(10, 50, 5)
   )
   results = cerebro.run(maxcpus=4)  # Use 4 CPUs

Visualization Issues
--------------------

Q: How do I save charts to a file?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # Matplotlib
   import matplotlib.pyplot as plt
   cerebro.plot()
   plt.savefig('chart.png', dpi=300)
   
   # Plotly
   from backtrader.plot import PlotlyPlot
   plotter = PlotlyPlot()
   figs = plotter.plot(results[0])
   figs[0].write_html('chart.html')

Q: How do I hide certain indicators from the chart?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   self.sma = bt.indicators.SMA(period=20)
   self.sma.plotinfo.plot = False  # Hide from chart

Analysis Issues
---------------

Q: How do I get the Sharpe ratio?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
   results = cerebro.run()
   sharpe = results[0].analyzers.sharpe.get_analysis()
   print(f"Sharpe Ratio: {sharpe.get('sharperatio', 'N/A')}")

Q: How do I get all trade details?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
   cerebro.addanalyzer(bt.analyzers.Transactions, _name='txn')
   
   results = cerebro.run()
   trades = results[0].analyzers.trades.get_analysis()
   transactions = results[0].analyzers.txn.get_analysis()

Q: How do I calculate maximum drawdown?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
   results = cerebro.run()
   dd = results[0].analyzers.dd.get_analysis()
   print(f"Max Drawdown: {dd['max']['drawdown']:.2f}%")

Multi-Timeframe Issues
-----------------------

Q: How do I use multiple timeframes?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # Add base data (e.g., 1-minute)
   data0 = bt.feeds.GenericCSVData(dataname='data_1min.csv')
   cerebro.adddata(data0)
   
   # Resample to higher timeframes
   cerebro.resampledata(data0, timeframe=bt.TimeFrame.Minutes, compression=5)
   cerebro.resampledata(data0, timeframe=bt.TimeFrame.Days, compression=1)
   
   class MultiTFStrategy(bt.Strategy):
       def next(self):
           # Access different timeframes
           data_1min = self.datas[0]
           data_5min = self.datas[1]
           data_daily = self.datas[2]

Q: Why isn't my resampled data aligned?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is a common issue. Key points:

- Higher timeframe bars are only considered complete when the next base bar arrives
- For live trading, use ``cerebro.run(runonce=False)`` for precise timing

Getting Help
------------

- **Documentation**: https://backtrader.readthedocs.io/
- **Author's Blog**: https://yunjinqi.blog.csdn.net/
- **GitHub Issues**: https://github.com/cloudQuant/backtrader/issues
- **Gitee Issues**: https://gitee.com/yunjinqi/backtrader/issues

See Also
--------

- :doc:`concepts/concepts` - Core Concepts
- :doc:`strategies/strategies` - Strategy Development
