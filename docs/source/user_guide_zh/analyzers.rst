======
分析器
======

使用分析器
----------

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # 添加分析器
   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
   cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
   cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
   
   # 运行
   results = cerebro.run()
   strat = results[0]
   
   # 获取结果
   print(strat.analyzers.sharpe.get_analysis())
   print(strat.analyzers.drawdown.get_analysis())
   print(strat.analyzers.trades.get_analysis())

常用分析器
----------

SharpeRatio（夏普比率）
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   cerebro.addanalyzer(
       bt.analyzers.SharpeRatio,
       _name='sharpe',
       timeframe=bt.TimeFrame.Days,
       riskfreerate=0.0,
       annualize=True
   )

DrawDown（最大回撤）
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
   
   # 访问结果
   dd = strat.analyzers.dd.get_analysis()
   print(f"最大回撤: {dd.max.drawdown:.2f}%")
   print(f"最长回撤周期: {dd.max.len} 根K线")

TradeAnalyzer（交易分析）
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='ta')
   
   ta = strat.analyzers.ta.get_analysis()
   print(f"总交易次数: {ta.total.total}")
   print(f"盈利次数: {ta.won.total}")
   print(f"亏损次数: {ta.lost.total}")
   print(f"胜率: {ta.won.total / ta.total.total:.2%}")

创建自定义分析器
----------------

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
           # 计算最终指标
           if self.trades:
               pnls = [t['pnl'] for t in self.trades]
               self.rets['total_pnl'] = sum(pnls)
               self.rets['avg_pnl'] = sum(pnls) / len(pnls)
               self.rets['num_trades'] = len(self.trades)
           self.rets['equity_curve'] = self.equity_curve
       
       def get_analysis(self):
           return self.rets

打印结果
--------

.. code-block:: python

   def print_analysis(results):
       strat = results[0]
       
       # 夏普比率
       sharpe = strat.analyzers.sharpe.get_analysis()
       print(f"夏普比率: {sharpe.get('sharperatio', 'N/A')}")
       
       # 回撤
       dd = strat.analyzers.drawdown.get_analysis()
       print(f"最大回撤: {dd.max.drawdown:.2f}%")
       
       # 交易
       ta = strat.analyzers.trades.get_analysis()
       print(f"总交易次数: {ta.total.total}")
       
       if ta.won.total > 0:
           print(f"胜率: {ta.won.total/ta.total.total:.2%}")
           print(f"平均盈利: {ta.won.pnl.average:.2f}")
       
       if ta.lost.total > 0:
           print(f"平均亏损: {ta.lost.pnl.average:.2f}")
