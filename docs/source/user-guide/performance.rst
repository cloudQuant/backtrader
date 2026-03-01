==========
性能优化
==========

在处理大型数据集或运行多个参数组合时，优化回测性能至关重要。
本指南介绍最大化 Backtrader 速度和效率的技术。

执行模式
--------

Backtrader 支持两种具有不同性能特征的执行模式：

runonce 模式（向量化）
^^^^^^^^^^^^^^^^^^^^^^

默认模式，在运行策略之前预先计算所有指标。适用于大多数回测场景。

.. code-block:: python

   cerebro.run(runonce=True)  # 默认

runnext 模式（事件驱动）
^^^^^^^^^^^^^^^^^^^^^^^^

逐K线处理数据。用于实盘交易或复杂订单逻辑。

.. code-block:: python

   cerebro.run(runonce=False)

.. tip::
   回测时使用 ``runonce=True``（默认）。只有在需要逐K线处理或进行实盘交易时
   才切换到 ``runonce=False``。

Python 版本
-----------

使用 Python 3.11+ 可以提供约 15-20% 的速度提升：

.. code-block:: bash

   # 安装 Python 3.11
   # 运行策略
   python3.11 your_strategy.py

数据加载优化
------------

使用高效数据格式
^^^^^^^^^^^^^^^^

.. code-block:: python

   import pickle
   import pandas as pd
   
   # 保存为 pickle（比 CSV 快）
   df = pd.read_csv('data.csv', parse_dates=['datetime'])
   df.to_pickle('data.pkl')
   
   # 从 pickle 加载
   df = pd.read_pickle('data.pkl')
   data = bt.feeds.PandasData(dataname=df)

预加载数据
^^^^^^^^^^

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # 预加载数据以加快访问
   cerebro.adddata(data)
   cerebro.run(preload=True)  # 默认为 True

限制数据范围
^^^^^^^^^^^^

.. code-block:: python

   from datetime import datetime
   
   data = bt.feeds.GenericCSVData(
       dataname='data.csv',
       fromdate=datetime(2020, 1, 1),
       todate=datetime(2023, 12, 31)
   )

指标优化
--------

使用内置指标
^^^^^^^^^^^^

内置指标已经过优化。避免重新创建它们：

.. code-block:: python

   # 好 - 使用内置
   self.sma = bt.indicators.SMA(period=20)
   
   # 差 - 手动计算
   def next(self):
       total = sum(self.data.close.get(size=20))
       self.manual_sma = total / 20

减少指标计算
^^^^^^^^^^^^

.. code-block:: python

   class EfficientStrategy(bt.Strategy):
       def __init__(self):
           # 在 __init__ 中计算一次，而不是在 next() 中
           self.sma = bt.indicators.SMA(period=20)
           self.rsi = bt.indicators.RSI(period=14)
           
           # 预计算信号
           self.signal = bt.indicators.CrossOver(
               self.data.close, self.sma
           )
       
       def next(self):
           # 只检查信号
           if self.signal > 0:
               self.buy()

缓存昂贵计算
^^^^^^^^^^^^

.. code-block:: python

   class CachedStrategy(bt.Strategy):
       def __init__(self):
           self._cache = {}
       
       def expensive_calculation(self, key):
           if key not in self._cache:
               self._cache[key] = self._do_calculation(key)
           return self._cache[key]

并行优化
--------

使用多 CPU
^^^^^^^^^^

.. code-block:: python

   import multiprocessing
   
   cerebro = bt.Cerebro()
   cerebro.optstrategy(
       MyStrategy,
       fast_period=range(5, 20, 5),
       slow_period=range(20, 60, 10)
   )
   
   # 使用所有 CPU
   results = cerebro.run(maxcpus=None)
   
   # 或指定 CPU 数量
   results = cerebro.run(maxcpus=4)

优化并行内存
^^^^^^^^^^^^

.. code-block:: python

   cerebro = bt.Cerebro(
       optdatas=True,     # 优化数据克隆
       optreturn=True     # 返回最小结果
   )

Cython 加速
-----------

对于计算密集型指标，使用 Cython：

.. code-block:: python

   # 安装 Cython
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

Numba 加速
----------

使用 Numba 进行 JIT 编译：

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

内存优化
--------

减少内存使用
^^^^^^^^^^^^

.. code-block:: python

   cerebro = bt.Cerebro(
       exactbars=True,    # 最小化K线内存
       stdstats=False     # 禁用标准观察者
   )

在自定义类中使用 __slots__
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   class MemoryEfficientIndicator(bt.Indicator):
       __slots__ = ['_cache', '_last_value']
       lines = ('signal',)
       
       def __init__(self):
           self._cache = None
           self._last_value = 0.0

清理未使用数据
^^^^^^^^^^^^^^

.. code-block:: python

   def stop(self):
       # 清理缓存
       self._cache.clear()
       
       # 如果需要强制垃圾回收
       import gc
       gc.collect()

性能分析
--------

识别瓶颈
^^^^^^^^

.. code-block:: python

   import cProfile
   import pstats
   
   # 分析回测
   profiler = cProfile.Profile()
   profiler.enable()
   
   results = cerebro.run()
   
   profiler.disable()
   stats = pstats.Stats(profiler)
   stats.sort_stats('cumulative')
   stats.print_stats(20)  # 前 20 个函数

计时特定部分
^^^^^^^^^^^^

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
           # 你的逻辑
           self.next_time += time.time() - start
       
       def stop(self):
           total = time.time() - self.start_time
           print(f'总计: {total:.2f}秒, next(): {self.next_time:.2f}秒')

性能对比表
----------

.. list-table::
   :widths: 30 20 50
   :header-rows: 1

   * - 优化项
     - 加速倍数
     - 说明
   * - Python 3.11+
     - ~15-20%
     - 简单，无需修改代码
   * - runonce=True
     - ~2-5倍
     - 默认模式
   * - Pickle 数据格式
     - ~3-10倍
     - 用于数据加载
   * - maxcpus（并行）
     - ~N倍
     - N = CPU 数量
   * - Cython 指标
     - ~10-100倍
     - 用于自定义指标
   * - Numba JIT
     - ~10-50倍
     - 比 Cython 更简单

最佳实践总结
------------

1. **使用 Python 3.11+** 获得约 15% 的速度提升
2. **保持 runonce=True** 用于回测
3. **使用 pickle 加载数据** 而不是 CSV
4. **尽可能使用内置指标**
5. **在 ``__init__()`` 中预计算信号**
6. **使用 maxcpus** 进行参数优化
7. **先分析再优化** 找到真正的瓶颈

参见
----

- :doc:`optimization` - 参数优化
- :doc:`indicators` - 指标开发
