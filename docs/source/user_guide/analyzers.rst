=========
Analyzers
=========

Using Analyzers
---------------

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # Add analyzers
   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
   cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
   cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
   
   # Run
   results = cerebro.run()
   strat = results[0]
   
   # Get results
   print(strat.analyzers.sharpe.get_analysis())
   print(strat.analyzers.drawdown.get_analysis())
   print(strat.analyzers.trades.get_analysis())

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
