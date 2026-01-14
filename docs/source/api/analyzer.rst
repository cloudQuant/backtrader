========
Analyzer
========

The ``Analyzer`` class is the base class for performance analysis tools.

.. automodule:: backtrader.analyzer
   :members:
   :undoc-members:
   :show-inheritance:
   :no-index:

Overview
--------

Analyzers calculate performance metrics and statistics during backtesting.
They can track trades, calculate returns, and compute various ratios.

Built-in Analyzers
------------------

Returns
~~~~~~~

- ``Returns``: Calculate returns over different periods
- ``TimeReturn``: Time-based returns
- ``LogReturnsRolling``: Rolling log returns

Risk Metrics
~~~~~~~~~~~~

- ``SharpeRatio``: Sharpe ratio calculation
- ``SortinoRatio``: Sortino ratio calculation
- ``Calmar``: Calmar ratio
- ``VWR``: Variability-Weighted Return

Drawdown
~~~~~~~~

- ``DrawDown``: Maximum drawdown analysis
- ``TimeDrawDown``: Time in drawdown

Trade Analysis
~~~~~~~~~~~~~~

- ``TradeAnalyzer``: Comprehensive trade statistics
- ``Transactions``: Transaction log
- ``PyFolio``: Integration with pyfolio

Position
~~~~~~~~

- ``PositionsValue``: Track position values
- ``GrossLeverage``: Leverage analysis

Using Analyzers
---------------

.. code-block:: python

   import backtrader as bt
   
   cerebro = bt.Cerebro()
   
   # Add analyzers
   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
   cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
   
   # Run backtest
   results = cerebro.run()
   strat = results[0]
   
   # Get analyzer results
   sharpe = strat.analyzers.sharpe.get_analysis()
   drawdown = strat.analyzers.drawdown.get_analysis()
   trades = strat.analyzers.trades.get_analysis()
   
   print(f"Sharpe Ratio: {sharpe['sharperatio']}")
   print(f"Max Drawdown: {drawdown['max']['drawdown']}%")
   print(f"Total Trades: {trades['total']['total']}")

Creating Custom Analyzers
-------------------------

.. code-block:: python

   class MyAnalyzer(bt.Analyzer):
       def __init__(self):
           self.trade_count = 0
           self.win_count = 0
       
       def notify_trade(self, trade):
           if trade.isclosed:
               self.trade_count += 1
               if trade.pnl > 0:
                   self.win_count += 1
       
       def stop(self):
           if self.trade_count > 0:
               win_rate = self.win_count / self.trade_count
           else:
               win_rate = 0
           self.rets['win_rate'] = win_rate
           self.rets['total_trades'] = self.trade_count
       
       def get_analysis(self):
           return self.rets
