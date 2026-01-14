======
数据源
======

加载CSV数据
-----------

通用CSV
~~~~~~~

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
