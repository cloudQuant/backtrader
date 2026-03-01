========
参数优化
========

参数优化帮助找到最佳策略参数。需要在高普适性和高效率之间权衡。

.. warning::
   作者建议使用自定义多进程进行优化，而不是 ``cerebro.optstrategy()``，
   因为偶尔会出现优化结果与单次运行结果不一致的bug。

内置优化
--------

使用 ``optstrategy`` 的基本用法：

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # 添加带参数范围的策略
   cerebro.optstrategy(
       MyStrategy,
       period=range(10, 31, 5),  # 10, 15, 20, 25, 30
       stake=[10, 20, 50]
   )
   
   # 运行优化
   results = cerebro.run()
   
   # 处理结果
   for run in results:
       for strat in run:
           print(f'周期: {strat.params.period}, 仓位: {strat.params.stake}')
           print(f'最终资金: {strat.broker.getvalue()}')

多核优化
--------

.. code-block:: python

   cerebro = bt.Cerebro(maxcpus=4)  # 使用4核
   # 或者
   cerebro = bt.Cerebro(maxcpus=None)  # 使用所有可用核心

获取最优参数
------------

.. code-block:: python

   def run_optimization():
       cerebro = bt.Cerebro()
       cerebro.adddata(data)
       
       cerebro.optstrategy(
           MyStrategy,
           fast=range(5, 15),
           slow=range(20, 40, 5)
       )
       
       cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
       
       results = cerebro.run()
       
       # 找到最佳结果
       best = None
       best_sharpe = float('-inf')
       
       for run in results:
           for strat in run:
               sharpe = strat.analyzers.sharpe.get_analysis()
               ratio = sharpe.get('sharperatio', 0) or 0
               
               if ratio > best_sharpe:
                   best_sharpe = ratio
                   best = strat
       
       if best:
           print(f'最优参数: fast={best.params.fast}, slow={best.params.slow}')
           print(f'夏普比率: {best_sharpe:.4f}')
       
       return best

内存优化
--------

对于大规模优化：

.. code-block:: python

   cerebro = bt.Cerebro(
       optreturn=False,  # 不返回完整的策略对象
       maxcpus=4
   )

推荐：多进程优化
------------------

为了更可靠和灵活的优化，使用 Python 的 multiprocessing：

.. code-block:: python

   from multiprocessing import Pool
   from itertools import product
   import pandas as pd
   
   def run_strategy(params):
       '''使用给定参数运行单次回测'''
       period, stake = params
       
       cerebro = bt.Cerebro()
       cerebro.adddata(data)  # 你的数据
       cerebro.addstrategy(MyStrategy, period=period, stake=stake)
       cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
       cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
       cerebro.broker.setcash(100000)
       
       results = cerebro.run()
       strat = results[0]
       
       sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0) or 0
       max_dd = strat.analyzers.dd.get_analysis()['max']['drawdown']
       final_value = cerebro.broker.getvalue()
       
       return {
           'period': period,
           'stake': stake,
           'sharpe': sharpe,
           'max_dd': max_dd,
           'final_value': final_value
       }
   
   if __name__ == '__main__':
       # 定义参数网格
       periods = range(10, 31, 5)
       stakes = [10, 20, 50]
       param_grid = list(product(periods, stakes))
       
       # 并行运行
       with Pool(processes=4) as pool:
           results = pool.map(run_strategy, param_grid)
       
       # 转换为 DataFrame 进行分析
       df = pd.DataFrame(results)
       print(df.sort_values('sharpe', ascending=False).head(10))
       
       # 获取最优参数
       best = df.loc[df['sharpe'].idxmax()]
       print(f"最优: period={best['period']}, stake={best['stake']}")
       print(f"夏普比率: {best['sharpe']:.4f}")

滚动优化（Walk-Forward）
------------------------

.. code-block:: python

   def walk_forward(data, strategy_cls, param_ranges, 
                    train_period=252, test_period=63):
       results = []
       
       for start in range(0, len(data) - train_period - test_period, test_period):
           # 训练期
           train_start = start
           train_end = start + train_period
           
           # 测试期
           test_start = train_end
           test_end = test_start + test_period
           
           # 在训练数据上优化
           cerebro = bt.Cerebro()
           train_data = data[train_start:train_end]
           cerebro.adddata(train_data)
           cerebro.optstrategy(strategy_cls, **param_ranges)
           opt_results = cerebro.run()
           
           # 找到最优参数
           best_params = find_best_params(opt_results)
           
           # 在样本外数据上测试
           cerebro = bt.Cerebro()
           test_data = data[test_start:test_end]
           cerebro.adddata(test_data)
           cerebro.addstrategy(strategy_cls, **best_params)
           test_results = cerebro.run()
           
           results.append({
               'train_period': (train_start, train_end),
               'test_period': (test_start, test_end),
               'best_params': best_params,
               'test_results': test_results
           })
       
       return results

最佳实践
--------

1. **使用多进程**: 比内置的 ``optstrategy`` 更可靠
2. **谨慎设置 maxcpus**: 使用 ``maxcpus = cpu_count - 1`` 避免系统卡死
3. **使用 optreturn=False**: 对于大规模优化，减少内存使用
4. **验证结果**: 始终用单次运行验证优化结果
5. **避免过拟合**: 使用滚动优化或交叉验证
6. **保存结果**: 将优化结果输出到 CSV 以便后续分析

参见
----

- :doc:`performance` - 速度优化
- :doc:`analyzers` - 绩效指标
- `博客: 参数优化 <https://yunjinqi.blog.csdn.net/article/details/120400145>`_
