======
数据源
======

数据源是回测的基础。Backtrader 支持各种数据来源，包括 CSV 文件、Pandas DataFrame、
数据库和实时数据流。

.. tip::
   数据以 **Lines** 形式存储 - 可以理解为 Excel 表格，每个 Line 是一列
   （open, high, low, close 等），每个 bar 是一行。

数据源参数
--------

所有数据源的通用参数：

.. list-table::
   :widths: 25 15 60
   :header-rows: 1

   * - 参数
     - 默认值
     - 描述
   * - ``dataname``
     - None
     - **必填**。文件路径、DataFrame 或数据源标识符
   * - ``name``
     - ""
     - 数据源名称（用于图表和 ``getdatabyname``）
   * - ``fromdate``
     - 最小时间
     - 开始日期过滤 - 此日期之前的数据被忽略
   * - ``todate``
     - 最大时间
     - 结束日期过滤 - 此日期之后的数据被忽略
   * - ``timeframe``
     - Days
     - TimeFrame.Ticks/Seconds/Minutes/Days/Weeks/Months/Years
   * - ``compression``
     - 1
     - 每个逻辑 bar 包含的实际 bar 数量
   * - ``sessionstart``
     - None
     - 交易时段开始时间（用于重采样）
   * - ``sessionend``
     - None
     - 交易时段结束时间（用于重采样）

加载CSV数据
-----------

通用CSV
~~~~~~~

最灵活的 CSV 加载器 - 适用于任意列排列：

.. code-block:: python

   data = bt.feeds.GenericCSVData(
       dataname='data.csv',
       dtformat='%Y-%m-%d %H:%M:%S',
       datetime=0,
       open=1,
       high=2,
       low=3,
       close=4,
       volume=5,
       openinterest=-1,  # -1 表示不存在
       fromdate=datetime.datetime(2020, 1, 1),
       todate=datetime.datetime(2021, 1, 1)
   )

GenericCSVData 特有参数：

.. list-table::
   :widths: 25 15 60
   :header-rows: 1

   * - 参数
     - 默认值
     - 描述
   * - ``header``
     - True
     - 第一行包含列名
   * - ``separator``
     - ","
     - CSV 字段分隔符
   * - ``nullvalue``
     - NaN
     - 缺失数据的替代值
   * - ``dtformat``
     - "%Y-%m-%d %H:%M:%S"
     - 日期时间格式字符串
   * - ``tmformat``
     - "%H:%M:%S"
     - 时间格式（如果单独一列）
   * - ``datetime``
     - 0
     - 日期时间列索引
   * - ``open/high/low/close``
     - 1/2/3/4
     - OHLC 列索引
   * - ``volume``
     - 5
     - 成交量列索引
   * - ``openinterest``
     - 6
     - 持仓量列索引（-1 = 不存在）

Yahoo Finance 格式
~~~~~~~~~~~~~~~~~~

.. code-block:: python

   data = bt.feeds.YahooFinanceCSVData(
       dataname='AAPL.csv',
       reverse=False,
       adjclose=True
   )

从Pandas加载
------------

.. code-block:: python

   import pandas as pd
   
   df = pd.read_csv('data.csv')
   df['date'] = pd.to_datetime(df['date'])
   df.set_index('date', inplace=True)
   
   data = bt.feeds.PandasData(dataname=df)

自定义列映射：

.. code-block:: python

   class MyPandasData(bt.feeds.PandasData):
       lines = ('signal',)  # 添加自定义数据线
       params = (
           ('signal', -1),  # 列索引或名称
       )

多数据源
--------

.. code-block:: python

   # 添加多个品种
   data1 = bt.feeds.GenericCSVData(dataname='stock1.csv')
   data2 = bt.feeds.GenericCSVData(dataname='stock2.csv')
   
   cerebro.adddata(data1, name='stock1')
   cerebro.adddata(data2, name='stock2')
   
   # 在策略中使用
   class MultiStrategy(bt.Strategy):
       def __init__(self):
           self.stock1 = self.getdatabyname('stock1')
           self.stock2 = self.getdatabyname('stock2')
           
           # 或者通过索引
           self.d0 = self.datas[0]
           self.d1 = self.datas[1]

重采样
------

转换为更高的时间周期：

.. code-block:: python

   # 分钟数据
   data = bt.feeds.GenericCSVData(dataname='minute_data.csv')
   cerebro.adddata(data)
   
   # 重采样为15分钟
   cerebro.resampledata(data, timeframe=bt.TimeFrame.Minutes, compression=15)
   
   # 重采样为日线
   cerebro.resampledata(data, timeframe=bt.TimeFrame.Days)

数据回放
--------

回放模拟逐K线更新：

.. code-block:: python

   cerebro.replaydata(
       data,
       timeframe=bt.TimeFrame.Days,
       compression=1
   )

过滤器
------

应用数据过滤器：

.. code-block:: python

   # 交易时段过滤器 - 仅交易时间
   data.addfilter(bt.filters.SessionFilter)
   
   # 日历过滤器
   data.addfilter(bt.filters.CalendarDays)

自定义数据源
----------

扩展数据源以包含额外列（如 PE、PB 等基本面数据）：

.. code-block:: python

   class GenericCSV_PB_PE(bt.feeds.GenericCSVData):
       # 添加新的 lines（列）
       lines = ('pe_ratio', 'pb_ratio',)
       
       # 映射到 CSV 中的列索引（从0开始）
       params = (
           ('pe_ratio', 8),   # 第9列
           ('pb_ratio', 9),   # 第10列
       )
   
   # 使用
   data = GenericCSV_PB_PE(
       dataname='股票基本面数据.csv',
       dtformat='%Y-%m-%d'
   )
   cerebro.adddata(data, name='STOCK')
   
   # 在策略中访问
   class MyStrategy(bt.Strategy):
       def next(self):
           pe = self.data.pe_ratio[0]
           pb = self.data.pb_ratio[0]
           if pe < 10 and pb < 2:
               self.buy()

可复用的自定义数据类
~~~~~~~~~~~~~~~~~~

为你的数据格式创建可复用的类：

.. code-block:: python

   class MyDataFormat(bt.feeds.GenericCSVData):
       params = (
           ('dtformat', '%Y-%m-%d'),
           ('datetime', 0),
           ('open', 1),
           ('high', 2),
           ('low', 3),
           ('close', 4),
           ('volume', 5),
           ('openinterest', -1),
       )
   
   # 现在只需：
   data = MyDataFormat(dataname='any_file.csv')

在策略中访问数据
--------------

数据按添加顺序存储在 ``self.datas`` 列表中：

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def __init__(self):
           # 按索引（添加顺序）
           self.data0 = self.datas[0]  # 或 self.data0
           self.data1 = self.datas[1]  # 或 self.data1
           
           # 按名称（如果指定了 name）
           self.stock = self.getdatabyname('STOCK')
           
       def next(self):
           # 访问 OHLCV
           print(f"开盘价: {self.data.open[0]}")
           print(f"最高价: {self.data.high[0]}")
           print(f"最低价: {self.data.low[0]}")
           print(f"收盘价: {self.data.close[0]}")
           print(f"成交量: {self.data.volume[0]}")
           
           # 前一根 bar
           print(f"昨日收盘: {self.data.close[-1]}")

处理缺失数据
----------

对于多股票回测，某些股票可能有缺失数据（如停牌）：

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def next(self):
           for data in self.datas:
               # 检查当前 bar 数据是否有效
               if len(data) == 0:
                   continue
               
               # 检查 NaN 值
               if data.close[0] != data.close[0]:  # NaN 检查
                   continue
               
               # 处理有效数据
               self.process_data(data)

最佳实践
--------

1. **始终指定 fromdate/todate**: 限制内存使用并加快加载速度
2. **使用 name 参数**: 使多数据策略更清晰
3. **创建可复用的数据类**: 避免重复列映射
4. **验证数据**: 检查缺失值和日期缺口
5. **正确使用 timeframe**: 匹配数据的实际频率

参见
----

- :doc:`concepts` - Lines 数据结构
- :doc:`strategies` - 在策略中使用数据
- `博客: Feed讲解 <https://yunjinqi.blog.csdn.net/article/details/108983892>`_
- `博客: 扩展数据 <https://yunjinqi.blog.csdn.net/article/details/108991405>`_
