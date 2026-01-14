==========
Quickstart
==========

This guide will walk you through creating your first backtest.

Basic Structure
---------------

A typical backtest consists of:

1. Create a Cerebro engine
2. Add data
3. Add a strategy
4. Configure the broker
5. Run the backtest
6. Analyze results

Your First Backtest
-------------------

.. code-block:: python

   import backtrader as bt
   import datetime
   
   # Create a simple strategy
   class SmaCross(bt.Strategy):
       params = (('pfast', 10), ('pslow', 30),)
       
       def __init__(self):
           sma1 = bt.ind.SMA(period=self.p.pfast)
           sma2 = bt.ind.SMA(period=self.p.pslow)
           self.crossover = bt.ind.CrossOver(sma1, sma2)
       
       def next(self):
           if not self.position:
               if self.crossover > 0:
                   self.buy()
           elif self.crossover < 0:
               self.close()
   
   # Create cerebro
   cerebro = bt.Cerebro()
   
   # Add data
   data = bt.feeds.YahooFinanceCSVData(
       dataname='AAPL.csv',
       fromdate=datetime.datetime(2020, 1, 1),
       todate=datetime.datetime(2021, 1, 1)
   )
   cerebro.adddata(data)
   
   # Add strategy
   cerebro.addstrategy(SmaCross)
   
   # Set cash
   cerebro.broker.setcash(100000)
   
   # Add analyzer
   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
   
   # Run
   print(f'Starting Portfolio Value: {cerebro.broker.getvalue():.2f}')
   results = cerebro.run()
   print(f'Final Portfolio Value: {cerebro.broker.getvalue():.2f}')
   
   # Get analysis
   strat = results[0]
   print(f'Sharpe Ratio: {strat.analyzers.sharpe.get_analysis()}')
   
   # Plot
   cerebro.plot()

Understanding the Output
------------------------

After running:

- **Portfolio Value**: Shows profit/loss
- **Sharpe Ratio**: Risk-adjusted return metric
- **Chart**: Visual representation of trades

Next Steps
----------

- :doc:`concepts` - Learn core concepts
- :doc:`strategies` - Build complex strategies
- :doc:`indicators` - Use technical indicators
- :doc:`analyzers` - Analyze performance
