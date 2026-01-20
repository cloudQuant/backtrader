============
Optimization
============

Parameter optimization helps find the best strategy parameters. Choose wisely between
high generalizability and high efficiency.

.. warning::
   The author recommends using custom multiprocessing for optimization instead of
   ``cerebro.optstrategy()`` due to occasional bugs where optimization results
   differ from single-run results.

Built-in Optimization
---------------------

Basic usage with ``optstrategy``:

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # Add strategy with parameter ranges
   cerebro.optstrategy(
       MyStrategy,
       period=range(10, 31, 5),  # 10, 15, 20, 25, 30
       stake=[10, 20, 50]
   )
   
   # Run optimization
   results = cerebro.run()
   
   # Process results
   for run in results:
       for strat in run:
           print(f'Period: {strat.params.period}, Stake: {strat.params.stake}')
           print(f'Final Value: {strat.broker.getvalue()}')

Multi-Core Optimization
-----------------------

.. code-block:: python

   cerebro = bt.Cerebro(maxcpus=4)  # Use 4 cores
   # or
   cerebro = bt.Cerebro(maxcpus=None)  # Use all available cores

Getting Best Parameters
-----------------------

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
       
       # Find best result
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
           print(f'Best params: fast={best.params.fast}, slow={best.params.slow}')
           print(f'Sharpe Ratio: {best_sharpe:.4f}')
       
       return best

Memory Optimization
-------------------

For large optimizations:

.. code-block:: python

   cerebro = bt.Cerebro(
       optreturn=False,  # Don't return full strategy objects
       maxcpus=4
   )

Custom Return Objects
---------------------

.. code-block:: python

   cerebro = bt.Cerebro(optreturn=True)
   
   # Results will contain lightweight objects with:
   # - params: Strategy parameters
   # - analyzers: Analyzer results

Recommended: Multiprocessing Optimization
------------------------------------------

For more reliable and flexible optimization, use Python's multiprocessing:

.. code-block:: python

   from multiprocessing import Pool
   from itertools import product
   import pandas as pd
   
   def run_strategy(params):
       '''Run a single backtest with given parameters'''
       period, stake = params
       
       cerebro = bt.Cerebro()
       cerebro.adddata(data)  # Your data
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
       # Define parameter grid
       periods = range(10, 31, 5)
       stakes = [10, 20, 50]
       param_grid = list(product(periods, stakes))
       
       # Run in parallel
       with Pool(processes=4) as pool:
           results = pool.map(run_strategy, param_grid)
       
       # Convert to DataFrame for analysis
       df = pd.DataFrame(results)
       print(df.sort_values('sharpe', ascending=False).head(10))
       
       # Get best parameters
       best = df.loc[df['sharpe'].idxmax()]
       print(f"Best: period={best['period']}, stake={best['stake']}")
       print(f"Sharpe: {best['sharpe']:.4f}")

Walk-Forward Optimization
-------------------------

.. code-block:: python

   def walk_forward(data, strategy_cls, param_ranges, 
                    train_period=252, test_period=63):
       results = []
       
       for start in range(0, len(data) - train_period - test_period, test_period):
           # Training period
           train_start = start
           train_end = start + train_period
           
           # Test period
           test_start = train_end
           test_end = test_start + test_period
           
           # Optimize on training data
           cerebro = bt.Cerebro()
           train_data = data[train_start:train_end]
           cerebro.adddata(train_data)
           cerebro.optstrategy(strategy_cls, **param_ranges)
           opt_results = cerebro.run()
           
           # Find best params
           best_params = find_best_params(opt_results)
           
           # Test on out-of-sample data
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

Best Practices
--------------

1. **Use multiprocessing**: More reliable than built-in ``optstrategy``
2. **Set maxcpus carefully**: Use ``maxcpus = cpu_count - 1`` to avoid system freeze
3. **Use optreturn=False**: For large optimizations, reduces memory usage
4. **Validate results**: Always verify optimization results with single runs
5. **Avoid overfitting**: Use walk-forward or cross-validation
6. **Save results**: Output optimization results to CSV for later analysis

See Also
--------

- :doc:`performance` - Speed optimization
- :doc:`analyzers` - Performance metrics
- `Blog: Parameter Optimization <https://yunjinqi.blog.csdn.net/article/details/120400145>`_
