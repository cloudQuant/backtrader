======================
Performance Optimization
======================

Optimizing backtest performance is crucial when working with large datasets or
running many parameter combinations. This guide covers techniques to maximize
Backtrader's speed and efficiency.

Execution Modes
---------------

Backtrader supports two execution modes with different performance characteristics:

runonce Mode (Vectorized)
^^^^^^^^^^^^^^^^^^^^^^^^^

Default mode that pre-calculates all indicators before running the strategy.
Best for most backtesting scenarios.

.. code-block:: python

   cerebro.run(runonce=True)  # Default

runnext Mode (Event-driven)
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Processes data bar-by-bar. Required for live trading or complex order logic.

.. code-block:: python

   cerebro.run(runonce=False)

.. tip::
   Use ``runonce=True`` (default) for backtesting. Only switch to ``runonce=False``
   when you need bar-by-bar processing or are doing live trading.

Python Version
--------------

Using Python 3.11+ can provide ~15-20% speed improvement:

.. code-block:: bash

   # Install Python 3.11
   # Run your strategy
   python3.11 your_strategy.py

Data Loading Optimization
-------------------------

Use Efficient Data Formats
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   import pickle
   import pandas as pd
   
   # Save data as pickle (faster than CSV)
   df = pd.read_csv('data.csv', parse_dates=['datetime'])
   df.to_pickle('data.pkl')
   
   # Load from pickle
   df = pd.read_pickle('data.pkl')
   data = bt.feeds.PandasData(dataname=df)

Preload Data
^^^^^^^^^^^^

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # Preload data for faster access
   cerebro.adddata(data)
   cerebro.run(preload=True)  # Default is True

Limit Data Range
^^^^^^^^^^^^^^^^

.. code-block:: python

   from datetime import datetime
   
   data = bt.feeds.GenericCSVData(
       dataname='data.csv',
       fromdate=datetime(2020, 1, 1),
       todate=datetime(2023, 12, 31)
   )

Indicator Optimization
----------------------

Use Built-in Indicators
^^^^^^^^^^^^^^^^^^^^^^^

Built-in indicators are optimized. Avoid recreating them:

.. code-block:: python

   # Good - use built-in
   self.sma = bt.indicators.SMA(period=20)
   
   # Bad - manual calculation
   def next(self):
       total = sum(self.data.close.get(size=20))
       self.manual_sma = total / 20

Minimize Indicator Calculations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   class EfficientStrategy(bt.Strategy):
       def __init__(self):
           # Calculate once in __init__, not in next()
           self.sma = bt.indicators.SMA(period=20)
           self.rsi = bt.indicators.RSI(period=14)
           
           # Pre-compute signal
           self.signal = bt.indicators.CrossOver(
               self.data.close, self.sma
           )
       
       def next(self):
           # Just check the signal
           if self.signal > 0:
               self.buy()

Cache Expensive Calculations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   class CachedStrategy(bt.Strategy):
       def __init__(self):
           self._cache = {}
       
       def expensive_calculation(self, key):
           if key not in self._cache:
               self._cache[key] = self._do_calculation(key)
           return self._cache[key]

Parallel Optimization
---------------------

Use Multiple CPUs
^^^^^^^^^^^^^^^^^

.. code-block:: python

   import multiprocessing
   
   cerebro = bt.Cerebro()
   cerebro.optstrategy(
       MyStrategy,
       fast_period=range(5, 20, 5),
       slow_period=range(20, 60, 10)
   )
   
   # Use all CPUs
   results = cerebro.run(maxcpus=None)
   
   # Or specify number of CPUs
   results = cerebro.run(maxcpus=4)

Optimize Memory for Parallel
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   cerebro = bt.Cerebro(
       optdatas=True,     # Optimize data cloning
       optreturn=True     # Return minimal results
   )

Cython Acceleration
-------------------

For computationally intensive indicators, use Cython:

.. code-block:: python

   # Install Cython
   # pip install cython
   
   # fast_indicator.pyx
   cimport cython
   import numpy as np
   cimport numpy as np
   
   @cython.boundscheck(False)
   @cython.wraparound(False)
   def fast_sma(double[:] data, int period):
       cdef int n = len(data)
       cdef double[:] result = np.zeros(n)
       cdef double total = 0.0
       cdef int i
       
       for i in range(n):
           total += data[i]
           if i >= period:
               total -= data[i - period]
           if i >= period - 1:
               result[i] = total / period
       
       return np.asarray(result)

Numba Acceleration
------------------

Use Numba for JIT compilation:

.. code-block:: python

   from numba import jit
   import numpy as np
   
   @jit(nopython=True)
   def fast_rsi(prices, period=14):
       deltas = np.diff(prices)
       gains = np.where(deltas > 0, deltas, 0.0)
       losses = np.where(deltas < 0, -deltas, 0.0)
       
       avg_gain = np.mean(gains[:period])
       avg_loss = np.mean(losses[:period])
       
       rsi = np.zeros(len(prices))
       for i in range(period, len(prices)):
           avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
           avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
           
           if avg_loss == 0:
               rsi[i] = 100
           else:
               rs = avg_gain / avg_loss
               rsi[i] = 100 - (100 / (1 + rs))
       
       return rsi

Memory Optimization
-------------------

Reduce Memory Usage
^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   cerebro = bt.Cerebro(
       exactbars=True,    # Minimize memory for bars
       stdstats=False     # Disable standard observers
   )

Use __slots__ in Custom Classes
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   class MemoryEfficientIndicator(bt.Indicator):
       __slots__ = ['_cache', '_last_value']
       lines = ('signal',)
       
       def __init__(self):
           self._cache = None
           self._last_value = 0.0

Clear Unused Data
^^^^^^^^^^^^^^^^^

.. code-block:: python

   def stop(self):
       # Clear caches
       self._cache.clear()
       
       # Force garbage collection if needed
       import gc
       gc.collect()

Profiling
---------

Identify Bottlenecks
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   import cProfile
   import pstats
   
   # Profile the backtest
   profiler = cProfile.Profile()
   profiler.enable()
   
   results = cerebro.run()
   
   profiler.disable()
   stats = pstats.Stats(profiler)
   stats.sort_stats('cumulative')
   stats.print_stats(20)  # Top 20 functions

Time Specific Sections
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   import time
   
   class TimedStrategy(bt.Strategy):
       def __init__(self):
           self.init_time = 0
           self.next_time = 0
           self.start_time = time.time()
       
       def prenext(self):
           pass
       
       def next(self):
           start = time.time()
           # Your logic here
           self.next_time += time.time() - start
       
       def stop(self):
           total = time.time() - self.start_time
           print(f'Total: {total:.2f}s, next(): {self.next_time:.2f}s')

Performance Comparison Table
----------------------------

.. list-table::
   :widths: 30 20 50
   :header-rows: 1

   * - Optimization
     - Speedup
     - Notes
   * - Python 3.11+
     - ~15-20%
     - Easy, no code changes
   * - runonce=True
     - ~2-5x
     - Default mode
   * - Pickle data format
     - ~3-10x
     - For data loading
   * - maxcpus (parallel)
     - ~Nx
     - N = number of CPUs
   * - Cython indicators
     - ~10-100x
     - For custom indicators
   * - Numba JIT
     - ~10-50x
     - Easier than Cython

Best Practices Summary
----------------------

1. **Use Python 3.11+** for ~15% speed boost
2. **Keep runonce=True** for backtesting
3. **Load data as pickle** instead of CSV
4. **Use built-in indicators** when possible
5. **Pre-compute signals** in ``__init__()``
6. **Use maxcpus** for parameter optimization
7. **Profile before optimizing** to find real bottlenecks

See Also
--------

- :doc:`optimization` - Parameter optimization
- :doc:`indicators` - Indicator development
