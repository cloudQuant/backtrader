==============
分析器与报告
==============

分析器是评估策略绩效的必要工具。Backtrader 提供 17+ 内置分析器，
并支持自定义分析器用于特殊指标计算。

快速开始
--------

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # 添加分析器
   cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
   cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
   cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
   cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
   cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
   
   # 运行回测
   results = cerebro.run()
   strat = results[0]
   
   # 获取结果
   print(f"夏普比率: {strat.analyzers.sharpe.get_analysis().get('sharperatio', 'N/A')}")
   print(f"最大回撤: {strat.analyzers.drawdown.get_analysis()['max']['drawdown']:.2f}%")
   print(f"SQN: {strat.analyzers.sqn.get_analysis()['sqn']:.2f}")

内置分析器
----------

.. list-table::
   :widths: 25 75
   :header-rows: 1

   * - 分析器
     - 用途
   * - SharpeRatio
     - 风险调整收益（夏普比率）
   * - DrawDown
     - 最大回撤分析
   * - TradeAnalyzer
     - 全面交易统计
   * - Returns
     - 收益率计算
   * - SQN
     - 系统质量数
   * - Calmar
     - 卡玛比率（收益/最大回撤）
   * - VWR
     - 波动率加权收益
   * - TimeReturn
     - 分周期收益
   * - AnnualReturn
     - 年度收益明细
   * - Transactions
     - 所有交易详情
   * - PeriodStats
     - 分周期统计指标
   * - PositionsValue
     - 持仓价值跟踪
   * - PyFolio
     - pyfolio 兼容输出

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

专业报告
--------

Backtrader 可以一键生成全面的 HTML 报告。

一键生成报告
~~~~~~~~~~~~

.. code-block:: python

   # 添加报告分析器
   cerebro.add_report_analyzers(riskfree_rate=0.02)
   
   # 运行回测
   results = cerebro.run()
   
   # 生成 HTML 报告
   cerebro.generate_report(
       filename='backtest_report.html',
       user='交易员名称',
       memo='SMA 金叉死叉策略分析',
       strategy_name='SMA Cross'
   )

报告内容
~~~~~~~~

生成的报告包含：

- **汇总统计**：总收益率、夏普比率、卡玛比率、SQN
- **资金曲线**：交互式投资组合价值图表
- **回撤分析**：最大回撤图表和持续时间
- **交易统计**：胜率、盈利因子、平均交易
- **月度收益**：月度绩效热力图
- **持仓详情**：入场/出场价格和盈亏

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

导出为 DataFrame
~~~~~~~~~~~~~~~~

.. code-block:: python

   import pandas as pd
   
   # 获取交易记录为 DataFrame
   cerebro.addanalyzer(bt.analyzers.Transactions, _name='txn')
   results = cerebro.run()
   
   txn = results[0].analyzers.txn.get_analysis()
   df = pd.DataFrame.from_dict(txn, orient='index')
   df.to_csv('transactions.csv')

参见
----

- :doc:`visualization` - 图表绘制
- :doc:`strategies` - 策略开发
- :doc:`optimization` - 参数优化
- `博客: Analyzer使用教程 <https://yunjinqi.blog.csdn.net/article/details/109787656>`_
- `博客: 内置Analyzers详解 <https://yunjinqi.blog.csdn.net/article/details/122198829>`_
