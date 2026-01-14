==========
Data Feeds
==========

Loading CSV Data
----------------

Generic CSV
~~~~~~~~~~~

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
       openinterest=-1,  # -1 means not present
       fromdate=datetime.datetime(2020, 1, 1),
       todate=datetime.datetime(2021, 1, 1)
   )

Yahoo Finance Format
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   data = bt.feeds.YahooFinanceCSVData(
       dataname='AAPL.csv',
       reverse=False,
       adjclose=True
   )

Loading from Pandas
-------------------

.. code-block:: python

   import pandas as pd
   
   df = pd.read_csv('data.csv')
   df['date'] = pd.to_datetime(df['date'])
   df.set_index('date', inplace=True)
   
   data = bt.feeds.PandasData(dataname=df)

Custom column mapping:

.. code-block:: python

   class MyPandasData(bt.feeds.PandasData):
       lines = ('signal',)  # Add custom line
       params = (
           ('signal', -1),  # Column index or name
       )

Multiple Data Feeds
-------------------

.. code-block:: python

   # Add multiple instruments
   data1 = bt.feeds.GenericCSVData(dataname='stock1.csv')
   data2 = bt.feeds.GenericCSVData(dataname='stock2.csv')
   
   cerebro.adddata(data1, name='stock1')
   cerebro.adddata(data2, name='stock2')
   
   # In strategy
   class MultiStrategy(bt.Strategy):
       def __init__(self):
           self.stock1 = self.getdatabyname('stock1')
           self.stock2 = self.getdatabyname('stock2')
           
           # Or by index
           self.d0 = self.datas[0]
           self.d1 = self.datas[1]

Resampling
----------

Convert to higher timeframe:

.. code-block:: python

   # Minute data
   data = bt.feeds.GenericCSVData(dataname='minute_data.csv')
   cerebro.adddata(data)
   
   # Resample to 15 minutes
   cerebro.resampledata(data, timeframe=bt.TimeFrame.Minutes, compression=15)
   
   # Resample to daily
   cerebro.resampledata(data, timeframe=bt.TimeFrame.Days)

Replaying Data
--------------

Replay simulates bar-by-bar updates:

.. code-block:: python

   cerebro.replaydata(
       data,
       timeframe=bt.TimeFrame.Days,
       compression=1
   )

Filters
-------

Apply data filters:

.. code-block:: python

   # Session filter - only trading hours
   data.addfilter(bt.filters.SessionFilter)
   
   # Calendar filter
   data.addfilter(bt.filters.CalendarDays)
