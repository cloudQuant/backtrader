==========
Quickstart
==========

This guide will walk you through creating your first backtest in 5 minutes.

Installation
------------

First, install Backtrader:

.. code-block:: bash

   pip install backtrader

For development installation:

.. code-block:: bash

   git clone https://github.com/cloudQuant/backtrader.git
   cd backtrader
   pip install -e .

Basic Structure
---------------

A typical backtest consists of:

1. Create a Cerebro engine
2. Add data feeds
3. Add a strategy
4. Configure the broker
5. Run the backtest
6. Analyze results

Your First Backtest
-------------------

Let's create a simple moving average crossover strategy:

.. code-block:: python

   import backtrader as bt
   from datetime import datetime

   # Define Strategy
   class SmaCrossStrategy(bt.Strategy):
       """
       A simple moving average crossover strategy.

       Rules:
       - Buy when fast MA crosses above slow MA
       - Sell (close position) when fast MA crosses below slow MA
       """
       params = (
           ('fast_period', 10),   # Fast moving average period
           ('slow_period', 30),   # Slow moving average period
       )

       def __init__(self):
           # IMPORTANT: Always call super().__init__() first
           super().__init__()

           # Create indicators
           self.fast_ma = bt.indicators.SMA(period=self.params.fast_period)
           self.slow_ma = bt.indicators.SMA(period=self.params.slow_period)

           # Crossover indicator: >0 means cross up, <0 means cross down
           self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)

       def next(self):
           """Called for each bar in the data series."""
           # If no position, check for buy signal
           if not self.position:
               if self.crossover > 0:  # Fast MA crossed above slow MA
                   self.buy(size=100)
           # If in position, check for sell signal
           elif self.crossover < 0:  # Fast MA crossed below slow MA
               self.close()  # Close existing position

   # Create Cerebro Engine
   cerebro = bt.Cerebro()

   # Add Data Feed
   # Using generic CSV data - replace with your data file
   data = bt.feeds.GenericCSVData(
       dataname='your_data.csv',
       datetime=0,      # Column index for datetime
       open=1,          # Column index for open
       high=2,          # Column index for high
       low=3,           # Column index for low
       close=4,         # Column index for close
       volume=5,        # Column index for volume
       dtformat='%Y-%m-%d',  # Date format
       fromdate=datetime(2020, 1, 1),
       todate=datetime(2023, 12, 31)
   )
   cerebro.adddata(data)

   # Add Strategy with custom parameters
   cerebro.addstrategy(SmaCrossStrategy, fast_period=10, slow_period=30)

   # Set Initial Cash
   cerebro.broker.setcash(100000.0)

   # Set Commission (0.1% per trade)
   cerebro.broker.setcommission(commission=0.001)

   # Add Analyzers
   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
   cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
   cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

   # Print Starting Portfolio Value
   print(f'Starting Portfolio Value: {cerebro.broker.getvalue():.2f}')

   # Run Backtest
   results = cerebro.run()
   strat = results[0]  # Get the first (and only) strategy instance

   # Print Final Portfolio Value
   print(f'Final Portfolio Value: {cerebro.broker.getvalue():.2f}')

   # Print Analysis Results
   print('\n=== Performance Metrics ===')

   # Sharpe Ratio
   sharpe_analysis = strat.analyzers.sharpe.get_analysis()
   if 'sharperatio' in sharpe_analysis:
       print(f"Sharpe Ratio: {sharpe_analysis['sharperatio']:.2f}")

   # Drawdown
   drawdown_analysis = strat.analyzers.drawdown.get_analysis()
   print(f"Max Drawdown: {drawdown_analysis['max']['drawdown']:.2f}%")
   print(f"Max Drawdown Duration: {drawdown_analysis['max']['len']} bars")

   # Returns
   returns_analysis = strat.analyzers.returns.get_analysis()
   print(f"Total Return: {returns_analysis.get('rtot', 0) * 100:.2f}%")
   print(f"Average Return (Annual): {returns_analysis.get('ravg', 0) * 100:.2f}%")

   # Trade Analysis
   trades_analysis = strat.analyzers.trades.get_analysis()
   if 'total' in trades_analysis:
       total_trades = trades_analysis['total']['total']
       won_trades = trades_analysis['won']['total']
       win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0
       print(f"\nTotal Trades: {total_trades}")
       print(f"Winning Trades: {won_trades}")
       print(f"Losing Trades: {trades_analysis['lost']['total']}")
       print(f"Win Rate: {win_rate:.2f}%")

   # Plot Results
   cerebro.plot(style='plotly')  # Interactive plotly chart
   # For static matplotlib plot:
   # cerebro.plot(style='matplotlib')

Understanding the Code
----------------------

Strategy Class
~~~~~~~~~~~~~~

- **params**: Define customizable parameters for your strategy
- **__init__**: Set up indicators and calculations (called once)
- **next**: Contains your trading logic (called for each bar)

Indicators
~~~~~~~~~~

- **SMA**: Simple Moving Average
- **CrossOver**: Signals when two lines cross (>0 = cross up, <0 = cross down)

Cerebro Methods
~~~~~~~~~~~~~~~

- **adddata()**: Add a data feed to the system
- **addstrategy()**: Add a strategy with parameters
- **broker.setcash()**: Set initial capital
- **broker.setcommission()**: Set trading commission
- **addanalyzer()**: Add performance analyzers
- **run()**: Execute the backtest
- **plot()**: Visualize results

Sample Data Format
------------------

Your CSV file should look like this:

.. code-block:: text

   2000-01-03,1450.00,1460.00,1440.00,1450.00,1000000
   2000-01-04,1460.00,1470.00,1450.00,1465.00,1200000
   ...

Columns: datetime, open, high, low, close, volume

Alternative Data Sources
------------------------

Yahoo Finance (Online):

.. code-block:: python

   data = bt.feeds.YahooFinanceData(
       dataname='AAPL',
       fromdate=datetime(2020, 1, 1),
       todate=datetime(2023, 12, 31)
   )

Pandas DataFrame:

.. code-block:: python

   import pandas as pd

   df = pd.read_csv('data.csv', parse_dates=['date'], index_col='date')
   data = bt.feeds.PandasData(dataname=df)

Common Issues
-------------

**"No data feeds" error**: Make sure you call ``adddata()`` before ``run()``

**Zero division in Sharpe Ratio**: Add more data or check risk-free rate setting

**Empty plot**: Check that your data has valid OHLCV values

**Strategy not trading**: Add print statements in ``next()`` to debug logic

Next Steps
----------

- :doc:`concepts` - Learn core concepts (Lines, Phases, Indicators)
- :doc:`strategies` - Build more complex strategies
- :doc:`indicators` - Explore 60+ built-in indicators
- :doc:`analyzers` - Deep dive into performance analysis
- :doc:`data_feeds` - All data feed options
- :doc:`visualization` - Advanced plotting options
