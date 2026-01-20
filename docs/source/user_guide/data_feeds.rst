==========
Data Feeds
==========

Data feeds are the foundation of backtesting. Backtrader supports various data sources
including CSV files, Pandas DataFrames, databases, and live data streams.

.. tip::
   Data is stored as **Lines** - think of it like an Excel spreadsheet where each Line
   is a column (open, high, low, close, etc.) and each bar is a row.

Data Feed Parameters
--------------------

Common parameters for all data feeds:

.. list-table::
   :widths: 25 15 60
   :header-rows: 1

   * - Parameter
     - Default
     - Description
   * - ``dataname``
     - None
     - **Required**. File path, DataFrame, or data source identifier
   * - ``name``
     - ""
     - Name for the data feed (used in plots and ``getdatabyname``)
   * - ``fromdate``
     - min datetime
     - Start date filter - data before this is ignored
   * - ``todate``
     - max datetime
     - End date filter - data after this is ignored
   * - ``timeframe``
     - Days
     - TimeFrame.Ticks/Seconds/Minutes/Days/Weeks/Months/Years
   * - ``compression``
     - 1
     - Number of actual bars per logical bar
   * - ``sessionstart``
     - None
     - Session start time (for resampling)
   * - ``sessionend``
     - None
     - Session end time (for resampling)

Loading CSV Data
----------------

Generic CSV
~~~~~~~~~~~

The most flexible CSV loader - works with any column arrangement:

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

GenericCSVData-specific parameters:

.. list-table::
   :widths: 25 15 60
   :header-rows: 1

   * - Parameter
     - Default
     - Description
   * - ``header``
     - True
     - First row contains column names
   * - ``separator``
     - ","
     - CSV field separator
   * - ``nullvalue``
     - NaN
     - Value to use for missing data
   * - ``dtformat``
     - "%Y-%m-%d %H:%M:%S"
     - Datetime format string
   * - ``tmformat``
     - "%H:%M:%S"
     - Time format (if separate column)
   * - ``datetime``
     - 0
     - Column index for datetime
   * - ``open/high/low/close``
     - 1/2/3/4
     - Column indices for OHLC
   * - ``volume``
     - 5
     - Column index for volume
   * - ``openinterest``
     - 6
     - Column index for OI (-1 = not present)

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

Custom Data Feeds
-----------------

Extend data feeds to include additional columns (e.g., PE ratio, PB ratio):

.. code-block:: python

   class GenericCSV_PB_PE(bt.feeds.GenericCSVData):
       # Add new lines (columns)
       lines = ('pe_ratio', 'pb_ratio',)
       
       # Map to column indices in CSV (0-indexed)
       params = (
           ('pe_ratio', 8),   # 9th column
           ('pb_ratio', 9),   # 10th column
       )
   
   # Usage
   data = GenericCSV_PB_PE(
       dataname='stock_with_fundamentals.csv',
       dtformat='%Y-%m-%d'
   )
   cerebro.adddata(data, name='STOCK')
   
   # Access in strategy
   class MyStrategy(bt.Strategy):
       def next(self):
           pe = self.data.pe_ratio[0]
           pb = self.data.pb_ratio[0]
           if pe < 10 and pb < 2:
               self.buy()

Reusable Custom Feed Class
~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a reusable class for your data format:

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
   
   # Now just use:
   data = MyDataFormat(dataname='any_file.csv')

Accessing Data in Strategy
--------------------------

Data is stored in ``self.datas`` list in the order added:

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def __init__(self):
           # By index (order added)
           self.data0 = self.datas[0]  # or self.data0
           self.data1 = self.datas[1]  # or self.data1
           
           # By name (if name was specified)
           self.stock = self.getdatabyname('STOCK')
           
       def next(self):
           # Access OHLCV
           print(f"Open: {self.data.open[0]}")
           print(f"High: {self.data.high[0]}")
           print(f"Low: {self.data.low[0]}")
           print(f"Close: {self.data.close[0]}")
           print(f"Volume: {self.data.volume[0]}")
           
           # Previous bar
           print(f"Yesterday close: {self.data.close[-1]}")

Handling Missing Data
---------------------

For multi-stock backtests, some stocks may have missing data (e.g., halted trading):

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def next(self):
           for data in self.datas:
               # Check if data is valid for current bar
               if len(data) == 0:
                   continue
               
               # Check for NaN values
               if data.close[0] != data.close[0]:  # NaN check
                   continue
               
               # Process valid data
               self.process_data(data)

Best Practices
--------------

1. **Always specify fromdate/todate**: Limits memory usage and speeds up loading
2. **Use name parameter**: Makes multi-data strategies clearer
3. **Create reusable feed classes**: Avoid repeating column mappings
4. **Validate data**: Check for missing values and date gaps
5. **Use timeframe correctly**: Match data's actual frequency

See Also
--------

- :doc:`concepts` - Lines data structure
- :doc:`strategies` - Using data in strategies
- `Blog: Feed讲解 <https://yunjinqi.blog.csdn.net/article/details/108983892>`_
- `Blog: 扩展数据 <https://yunjinqi.blog.csdn.net/article/details/108991405>`_
