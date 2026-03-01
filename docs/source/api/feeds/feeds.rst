===========
Data Feeds
===========

Data feeds provide market data to the backtesting engine.

.. automodule:: backtrader.feeds
   :members:
   :undoc-members:
   :show-inheritance:
   :no-index:

Overview
--------

Data feeds are the source of market data for strategies. Backtrader supports
various data formats and sources.

Built-in Data Feeds
-------------------

CSV Data
~~~~~~~~

- ``GenericCSVData``: Flexible CSV reader
- ``YahooFinanceCSVData``: Yahoo Finance format
- ``BacktraderCSVData``: Backtrader native format

Pandas
~~~~~~

- ``PandasData``: Load from pandas DataFrame
- ``PandasDirectData``: Direct DataFrame access

Live Data
~~~~~~~~~

- ``IBData``: Interactive Brokers
- ``OandaData``: OANDA forex
- ``CCXTData``: Cryptocurrency exchanges

Using CSV Data
--------------

.. code-block:: python

   # Generic CSV
   data = bt.feeds.GenericCSVData(
       dataname='data.csv',
       dtformat='%Y-%m-%d',
       datetime=0,
       open=1,
       high=2,
       low=3,
       close=4,
       volume=5,
       openinterest=-1
   )
   
   # Yahoo Finance CSV
   data = bt.feeds.YahooFinanceCSVData(
       dataname='AAPL.csv',
       fromdate=datetime(2020, 1, 1),
       todate=datetime(2021, 1, 1)
   )

Using Pandas Data
-----------------

.. code-block:: python

   import pandas as pd
   
   df = pd.read_csv('data.csv', parse_dates=['date'])
   df.set_index('date', inplace=True)
   
   data = bt.feeds.PandasData(
       dataname=df,
       datetime=None,  # Use index as datetime
       open='open',
       high='high',
       low='low',
       close='close',
       volume='volume'
   )

Resampling Data
---------------

.. code-block:: python

   # Load minute data
   data = bt.feeds.GenericCSVData(dataname='minute_data.csv')
   cerebro.adddata(data)
   
   # Resample to hourly
   cerebro.resampledata(
       data,
       timeframe=bt.TimeFrame.Minutes,
       compression=60
   )
   
   # Resample to daily
   cerebro.resampledata(
       data,
       timeframe=bt.TimeFrame.Days,
       compression=1
   )

Multiple Data Feeds
-------------------

.. code-block:: python

   # Add multiple stocks
   for symbol in ['AAPL', 'GOOGL', 'MSFT']:
       data = bt.feeds.YahooFinanceCSVData(
           dataname=f'{symbol}.csv'
       )
       cerebro.adddata(data, name=symbol)
   
   # Access in strategy
   class MyStrategy(bt.Strategy):
       def __init__(self):
           # Access by index
           self.data0 = self.datas[0]
           
           # Access by name
           self.aapl = self.getdatabyname('AAPL')
