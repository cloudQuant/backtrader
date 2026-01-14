========
参数优化
========

基本优化
--------

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
