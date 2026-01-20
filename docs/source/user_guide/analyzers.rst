==================
Analyzers & Reports
==================

Analyzers are essential tools for evaluating strategy performance. Backtrader provides
17+ built-in analyzers and supports custom analyzers for specialized metrics.

Quick Start
-----------

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # Add analyzers
   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
   cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
   cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
   cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
   
   # Run backtest
   results = cerebro.run()
   strat = results[0]
   
   # Get results
   print(f"Sharpe: {strat.analyzers.sharpe.get_analysis().get('sharperatio', 'N/A')}")
   print(f"Max DD: {strat.analyzers.drawdown.get_analysis()['max']['drawdown']:.2f}%")
   print(f"SQN: {strat.analyzers.sqn.get_analysis()['sqn']:.2f}")

Built-in Analyzers
------------------

.. list-table::
   :widths: 25 75
   :header-rows: 1

   * - Analyzer
     - Purpose
   * - SharpeRatio
     - Risk-adjusted returns
   * - DrawDown
     - Maximum drawdown analysis
   * - TradeAnalyzer
     - Comprehensive trade statistics
   * - Returns
     - Return calculations
   * - SQN
     - System Quality Number
   * - Calmar
     - Calmar ratio (return/max DD)
   * - VWR
     - Variability-Weighted Return
   * - TimeReturn
     - Period-based returns
   * - AnnualReturn
     - Yearly return breakdown
   * - Transactions
     - All transaction details
   * - PeriodStats
     - Statistical metrics by period
   * - PositionsValue
     - Position value tracking
   * - PyFolio
     - pyfolio-compatible output

Common Analyzers
----------------

SharpeRatio
~~~~~~~~~~~

.. code-block:: python

   cerebro.addanalyzer(
       bt.analyzers.SharpeRatio,
       _name='sharpe',
       timeframe=bt.TimeFrame.Days,
       riskfreerate=0.0,
       annualize=True
   )

DrawDown
~~~~~~~~

.. code-block:: python

   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
   
   # Access results
   dd = strat.analyzers.dd.get_analysis()
   print(f"Max Drawdown: {dd.max.drawdown:.2f}%")
   print(f"Max Duration: {dd.max.len} bars")

TradeAnalyzer
~~~~~~~~~~~~~

.. code-block:: python

   cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='ta')
   
   ta = strat.analyzers.ta.get_analysis()
   print(f"Total Trades: {ta.total.total}")
   print(f"Won: {ta.won.total}")
   print(f"Lost: {ta.lost.total}")
   print(f"Win Rate: {ta.won.total / ta.total.total:.2%}")

Creating Custom Analyzers
-------------------------

.. code-block:: python

   class MyAnalyzer(bt.Analyzer):
       def __init__(self):
           self.trades = []
           self.equity_curve = []
       
       def notify_trade(self, trade):
           if trade.isclosed:
               self.trades.append({
                   'pnl': trade.pnl,
                   'pnlcomm': trade.pnlcomm,
                   'barlen': trade.barlen,
               })
       
       def next(self):
           self.equity_curve.append(self._owner.broker.getvalue())
       
       def stop(self):
           # Calculate final metrics
           if self.trades:
               pnls = [t['pnl'] for t in self.trades]
               self.rets['total_pnl'] = sum(pnls)
               self.rets['avg_pnl'] = sum(pnls) / len(pnls)
               self.rets['num_trades'] = len(self.trades)
           self.rets['equity_curve'] = self.equity_curve
       
       def get_analysis(self):
           return self.rets

Professional Reports
--------------------

Backtrader can generate comprehensive HTML reports with a single command.

One-Click Report
~~~~~~~~~~~~~~~~

.. code-block:: python

   # Add report analyzers
   cerebro.add_report_analyzers(riskfree_rate=0.02)
   
   # Run backtest
   results = cerebro.run()
   
   # Generate HTML report
   cerebro.generate_report(
       filename='backtest_report.html',
       user='Trader Name',
       memo='SMA Crossover Strategy Analysis',
       strategy_name='SMA Cross'
   )

Report Contents
~~~~~~~~~~~~~~~

The generated report includes:

- **Summary Statistics**: Total return, Sharpe ratio, Calmar ratio, SQN
- **Equity Curve**: Interactive portfolio value chart
- **Drawdown Analysis**: Maximum drawdown chart and duration
- **Trade Statistics**: Win rate, profit factor, average trade
- **Monthly Returns**: Heatmap of monthly performance
- **Position Details**: Entry/exit prices and P&L

Printing Results
----------------

.. code-block:: python

   def print_analysis(results):
       strat = results[0]
       
       # Sharpe
       sharpe = strat.analyzers.sharpe.get_analysis()
       print(f"Sharpe Ratio: {sharpe.get('sharperatio', 'N/A')}")
       
       # Drawdown
       dd = strat.analyzers.drawdown.get_analysis()
       print(f"Max Drawdown: {dd.max.drawdown:.2f}%")
       
       # Trades
       ta = strat.analyzers.trades.get_analysis()
       print(f"Total Trades: {ta.total.total}")
       
       if ta.won.total > 0:
           print(f"Win Rate: {ta.won.total/ta.total.total:.2%}")
           print(f"Avg Win: {ta.won.pnl.average:.2f}")
       
       if ta.lost.total > 0:
           print(f"Avg Loss: {ta.lost.pnl.average:.2f}")

Export to DataFrame
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import pandas as pd
   
   # Get transactions as DataFrame
   cerebro.addanalyzer(bt.analyzers.Transactions, _name='txn')
   results = cerebro.run()
   
   txn = results[0].analyzers.txn.get_analysis()
   df = pd.DataFrame.from_dict(txn, orient='index')
   df.to_csv('transactions.csv')

See Also
--------

- :doc:`visualization` - Chart plotting
- :doc:`strategies` - Strategy development
- :doc:`optimization` - Parameter optimization
- `Blog: Analyzer使用教程 <https://yunjinqi.blog.csdn.net/article/details/109787656>`_
- `Blog: 内置Analyzers详解 <https://yunjinqi.blog.csdn.net/article/details/122198829>`_
