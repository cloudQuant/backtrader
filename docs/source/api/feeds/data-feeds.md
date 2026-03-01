- --

title: Data Feeds API
description: Complete Data Feed API reference for Backtrader

- --

# Data Feeds API

Data feeds are the source of price/volume data for backtesting and live trading in Backtrader. They provide OHLCV (Open, High, Low, Close, Volume, OpenInterest) data with datetime indexing.

## Class Hierarchy

```bash
AbstractDataBase (base class for all feeds)
    DataBase (full-featured data feed)
        CSVDataBase (CSV file parsing)
            GenericCSVData
            YahooFinanceCSVData
            BacktraderCSVData
        PandasData (DataFrame integration)
        CCXTFeed (cryptocurrency exchanges)
        ... and more

```bash

## Core Classes

### `backtrader.AbstractDataBase`

Base class for all data feed implementations.

```python
class backtrader.AbstractDataBase:
    """Base class for all data feed implementations."""

```bash

#### Parameters

| Parameter | Type | Default | Description |

|-----------|------|---------|-------------|

| `dataname` | Any | None | Data source identifier (filename, URL, DataFrame, etc.) |

| `name` | str | "" | Display name for the data feed |

| `compression` | int | 1 | Timeframe compression factor |

| `timeframe` | TimeFrame | TimeFrame.Days | TimeFrame period |

| `fromdate` | datetime | None | Start date for data filtering |

| `todate` | datetime | None | End date for data filtering |

| `sessionstart` | time | time.min | Session start time |

| `sessionend` | time | time(23, 59, 59, 999990) | Session end time |

| `tz` | str | None | Output timezone |

| `tzinput` | str | None | Input timezone |

| `calendar` | str/Calendar | None | Trading calendar to use |

#### Data Status States

| State | Description |

|-------|-------------|

| `CONNECTED` | Data feed is connected |

| `DISCONNECTED` | Data feed is disconnected |

| `CONNBROKEN` | Connection was broken |

| `DELAYED` | Data is delayed |

| `LIVE` | Live data is streaming |

| `NOTSUBSCRIBED` | Not subscribed to data |

| `NOTSUPPORTED_TF` | Timeframe not supported |

| `UNKNOWN` | Unknown status |

### `backtrader.DataBase`

Full-featured data feed class. Inherits all functionality from `AbstractDataBase`.

```python
class backtrader.DataBase(backtrader.AbstractDataBase):
    """Full-featured data feed class."""

```bash

## Line System

Data feeds use the "Line" system for time-series data access. Each data feed provides these lines:

### Standard Lines

| Line | Description |

|------|-------------|

| `datetime` | Timestamp of the bar |

| `open` | Opening price |

| `high` | Highest price |

| `low` | Lowest price |

| `close` | Closing price |

| `volume` | Trading volume |

| `openinterest` | Open interest (for derivatives) |

### Accessing Line Data

```python
class MyStrategy(bt.Strategy):
    def next(self):

# Current bar values (index 0)
        current_close = self.data.close[0]
        current_datetime = self.data.datetime.datetime(0)

# Previous bar values (negative indices)
        prev_close = self.data.close[-1]
        prev_high = self.data.high[-2]

# Length of data
        current_len = len(self.data)

```bash

### Data Indexing

| Index | Meaning |

|-------|---------|

| `0` | Current bar (most recent) |

| `-1` | Previous bar |

| `-2`, `-3`, ... | Historical bars |

| `1` | Next bar (only in replay/live scenarios) |

## TimeFrame

The `TimeFrame` class defines time periods for financial data.

### TimeFrame Constants

| Constant | Value | Description |

|----------|-------|-------------|

| `TimeFrame.Ticks` | 1 | Tick-level data |

| `TimeFrame.MicroSeconds` | 2 | Microseconds |

| `TimeFrame.Seconds` | 3 | Seconds |

| `TimeFrame.Minutes` | 4 | Minutes |

| `TimeFrame.Days` | 5 | Days |

| `TimeFrame.Weeks` | 6 | Weeks |

| `TimeFrame.Months` | 7 | Months |

| `TimeFrame.Years` | 8 | Years |

| `TimeFrame.NoTimeFrame` | 9 | No timeframe |

### TimeFrame Methods

```python

# Get name of timeframe

name = bt.TimeFrame.getname(bt.TimeFrame.Days)  # Returns 'Day'

name = bt.TimeFrame.getname(bt.TimeFrame.Minutes, 5)  # Returns 'Minutes'

# Get constant from name

tf = bt.TimeFrame.TFrame('Days')  # Returns TimeFrame.Days

# Get name from constant

name = bt.TimeFrame.TName(bt.TimeFrame.Days)  # Returns 'Days'

```bash

## Built-in Data Feeds

### CSV Feeds

#### GenericCSVData

Parses CSV files with configurable column mappings.

```python
data = bt.feeds.GenericCSVData(
    dataname='data.csv',
    datetime=0,      # Column index for datetime
    time=-1,         # Column index for time (-1 if none)
    open=1,          # Column index for open
    high=2,          # Column index for high
    low=3,           # Column index for low
    close=4,         # Column index for close
    volume=5,        # Column index for volume
    openinterest=6,  # Column index for open interest
    dtformat='%Y-%m-%d %H:%M:%S',  # Datetime format
    tmformat='%H:%M:%S',  # Time format
    nullvalue=float('NaN'),  # Value for missing fields
    separator=',',    # CSV separator
    headers=True,     # Skip first row if True

)

```bash

- *CSV Parameters:**

| Parameter | Type | Default | Description |

|-----------|------|---------|-------------|

| `dataname` | str/file | Required | CSV filename or file-like object |

| `datetime` | int | 0 | Column index for datetime |

| `time` | int | -1 | Column index for time (-1 if none) |

| `open` | int | 1 | Column index for open price |

| `high` | int | 2 | Column index for high price |

| `low` | int | 3 | Column index for low price |

| `close` | int | 4 | Column index for close price |

| `volume` | int | 5 | Column index for volume |

| `openinterest` | int | 6 | Column index for open interest |

| `dtformat` | str/int/callable | "%Y-%m-%d %H:%M:%S" | Datetime format or 1/2 for Unix timestamp |

| `tmformat` | str | "%H:%M:%S" | Time format |

| `nullvalue` | float | NaN | Value for missing fields |

| `separator` | str | "," | CSV separator character |

| `headers` | bool | True | Whether to skip first row |

- *dtformat Values:**

| Value | Meaning |

|-------|---------|

| `"%Y-%m-%d"` | String format for strptime |

| `1` | Unix timestamp (int, seconds since epoch) |

| `2` | Unix timestamp (float, seconds since epoch) |

| `callable` | Function that converts string to datetime |

#### YahooFinanceCSVData

Parses Yahoo Finance format CSV files.

```python
data = bt.feeds.YahooFinanceCSVData(
    dataname='yahoo.csv',
    reverse=False,     # Data is in chronological order
    adjclose=True,     # Use adjusted close prices
    adjvolume=True,    # Adjust volume when using adjclose
    round=True,        # Round prices
    decimals=2,        # Number of decimals for rounding

)

```bash

- *Yahoo CSV Parameters:**

| Parameter | Type | Default | Description |

|-----------|------|---------|-------------|

| `reverse` | bool | False | Set True if data is in reverse chronological order |

| `adjclose` | bool | True | Use dividend/split adjusted close |

| `adjvolume` | bool | True | Adjust volume based on adjustment factor |

| `round` | bool | True | Round prices to decimals |

| `decimals` | int | 2 | Number of decimals for rounding |

| `roundvolume` | int/bool | False | Round volume to N decimals |

#### BacktraderCSVData

Parses backtrader's test CSV format.

```python
data = bt.feeds.BacktraderCSVData(dataname='test.csv')

```bash
Format: `YYYY-MM-DD [HH:MM:SS] open high low close volume openinterest`

### Pandas Feeds

#### PandasData

Uses a pandas DataFrame as data source with column name matching.

```python
import pandas as pd

# Create DataFrame with standard column names

df = pd.DataFrame({
    'datetime': pd.date_range('2020-01-01', periods=100),
    'open': np.random.randn(100).cumsum() + 100,
    'high': np.random.randn(100).cumsum() + 102,
    'low': np.random.randn(100).cumsum() + 98,
    'close': np.random.randn(100).cumsum() + 100,
    'volume': np.random.randint(1000, 10000, 100),
})

# Use DataFrame as data feed

data = bt.feeds.PandasData(dataname=df)

# Or with custom column names

data = bt.feeds.PandasData(
    dataname=df,
    datetime=None,    # None means use index
    open='open_price',
    high='high_price',
    low='low_price',
    close='close_price',
    volume='vol',
    openinterest=None,  # None means column not present
    nocase=True,       # Case-insensitive column matching

)

```bash

- *PandasData Parameters:**

| Parameter | Type | Default | Description |

|-----------|------|---------|-------------|

| `dataname` | DataFrame | Required | Pandas DataFrame |

| `datetime` | None/int/str | None | Column for datetime (None = use index) |

| `open` | None/-1/int/str | -1 | Column for open price (-1 = auto-detect) |

| `high` | None/-1/int/str | -1 | Column for high price |

| `low` | None/-1/int/str | -1 | Column for low price |

| `close` | None/-1/int/str | -1 | Column for close price |

| `volume` | None/-1/int/str | -1 | Column for volume |

| `openinterest` | None/-1/int/str | -1 | Column for open interest |

| `nocase` | bool | True | Case-insensitive column matching |

- *Column Value Meanings:**

| Value | Meaning |

|-------|---------|

| `None` | Column not present in DataFrame |

| `-1` | Auto-detect column by name |

| `0, 1, 2...` | Numeric column index |

| `"column_name"` | String column name |

#### PandasDirectData

Uses DataFrame tuples directly for faster iteration.

```python
data = bt.feeds.PandasDirectData(
    dataname=df,  # DataFrame with column index positions
    datetime=0,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=6,
)

```bash

### Live/Online Feeds

#### CCXTFeed (Cryptocurrency)

Connects to cryptocurrency exchanges via CCXT library.

```python

# REST API polling

data = bt.feeds.CCXTFeed(
    exchange='binance',
    symbol='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    historical=False,      # Stop after historical download
    backfill_start=True,   # Backfill at start
    ohlcv_limit=100,       # Bars per request
    drop_newest=False,     # Drop most recent (possibly incomplete) bar

)

# With WebSocket (requires ccxt.pro)

data = bt.feeds.CCXTFeed(
    exchange='binance',
    symbol='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    use_websocket=True,           # Enable WebSocket
    ws_reconnect_delay=5.0,        # Reconnect delay (seconds)
    ws_max_reconnect_delay=60.0,   # Max reconnect delay

)

```bash

- *CCXTFeed Parameters:**

| Parameter | Type | Default | Description |

|-----------|------|---------|-------------|

| `exchange` | str | Required | Exchange name (binance, kraken, etc.) |

| `symbol` | str | Required | Trading pair (BTC/USDT, ETH/USD, etc.) |

| `historical` | bool | False | Stop after historical download |

| `backfill_start` | bool | True | Backfill historical data at start |

| `ohlcv_limit` | int | 100 | Max bars per REST request |

| `drop_newest` | bool | False | Drop most recent (incomplete) bar |

| `use_websocket` | bool | False | Use WebSocket for real-time data |

| `ws_reconnect_delay` | float | 5.0 | WebSocket reconnection delay |

| `ws_max_reconnect_delay` | float | 60.0 | Maximum reconnection delay |

#### YahooFinanceData

Direct download from Yahoo Finance (requires `requests` library).

```python
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',        # Ticker symbol
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31),
    timeframe=bt.TimeFrame.Days,
    period='d',             # 'd'=daily, 'w'=weekly, 'm'=monthly
    adjclose=True,          # Use adjusted close
    proxies={},             # Proxy configuration
    retries=3,              # Number of download retries

)

```bash

### Other Feeds

#### Quandl

```python
data = bt.feeds.Quandl(
    dataname='WIKI/AAPL',
    apikey='YOUR_API_KEY',
    fromdate=datetime(2020, 1, 1),
)

```bash

#### Interactive Brokers

```python
data = bt.feeds.IBData(
    dataname='AAPL',
    host='127.0.0.1',
    port=7496,
    clientId=1,
)

```bash

#### OANDA

```python
data = bt.feeds.OandaData(
    dataname='EUR_USD',
    account='YOUR_ACCOUNT',
    access_token='YOUR_TOKEN',
)

```bash

## Data Feed Methods

### Lifecycle Methods

#### `start(self)`

Called when backtesting begins. Opens files, connects to data sources.

```python

# Override in custom feed

class MyFeed(bt.CSVDataBase):
    def start(self):
        super().start()

# Custom initialization

```bash

#### `stop(self)`

Called when backtesting ends. Closes files, disconnects.

```python
def stop(self):

# Custom cleanup
    super().stop()

```bash

#### `preload(self)`

Loads all data into memory before backtesting.

```python

# Preloading is automatic with cerebro.run(preload=True)

data = bt.feeds.PandasData(dataname=df)
data.preload()  # Manual preload

```bash

### Data Access Methods

#### `date2num(self, dt)`

Convert datetime to internal numeric format.

```python
dt_num = data.date2num(datetime(2023, 1, 1))

```bash

#### `num2date(self, dt=None, tz=None, naive=True)`

Convert internal numeric format to datetime.

```python
dt = data.num2date()  # Current bar datetime

dt = data.num2date(data.lines.datetime[-1])  # Previous bar

```bash

### Cloning Methods

#### `clone(self, **kwargs)`

Create a clone of this data feed.

```python
data_clone = data.clone()  # Exact copy

data_clone = data.clone(timeframe=bt.TimeFrame.Weeks)  # Different timeframe

```bash

#### `copyas(self, _dataname, **kwargs)`

Copy with a different name.

```python
data_copy = data.copyas('AAPL_Copy')

```bash

### Status Methods

#### `islive(self)`

Returns True if this is a live data feed.

```python
if data.islive():
    print("This is a live data feed")

```bash

#### `haslivedata(self)`

Returns True if live data is available.

#### `get_notifications(self)`

Get pending status notifications.

```python
notifs = data.get_notifications()
for status, args, kwargs in notifs:
    print(f"Status: {status}")

```bash

## Data Filters

### Adding Filters

Filters modify or remove bars as they are loaded.

```python

# Add a simple filter

data.addfilter(lambda x: x.close[0] > x.open[0])  # Keep only green bars

# Add a filter class

data.addfilter(bt.filters.SessionData, session_end=time(15, 0))

```bash

### Built-in Filters

#### SessionFilter

Filters bars to specific trading session.

```python
data.addfilter(bt.filters.SessionFilter)

```bash

#### SessionData

Fills missing session data.

```python
data.addfilter(bt.filters.SessionData)

```bash

#### CalendarFilter

Filters based on trading calendar.

```python
data.addfilter(bt.filters.CalendarFilter)

```bash

## Resampling and Replay

### Resampling

Convert data to a different timeframe.

```python

# Resample minute data to hourly

data = bt.feeds.GenericCSVData(dataname='minute_data.csv')
data.resample(
    timeframe=bt.TimeFrame.Minutes,
    compression=60,  # 60 minutes = 1 hour

)

# In Cerebro

cerebro.resampledata(data, timeframe=bt.TimeFrame.Weeks, compression=1)

```bash

### Replay

Process tick data into bars with precise control.

```python
data.replay(
    timeframe=bt.TimeFrame.Minutes,
    compression=5,
    bar2edge=True,       # Align bars to timeframe boundary
    rightedge=True,      # Use right edge for timestamp
    boundoff=0,          # Offset from boundary

)

# In Cerebro

cerebro.replaydata(data, timeframe=bt.TimeFrame.Days)

```bash

## Custom Data Feed

### Creating a Custom CSV Feed

```python
import backtrader as bt
from datetime import datetime

class MyCSVData(bt.CSVDataBase):
    """Custom CSV parser for my data format."""

    params = (
        ('dtformat', '%d/%m/%Y'),
        ('separator', ';'),
    )

    def _loadline(self, linetokens):

# Parse datetime
        dt_str = linetokens[0]
        dt = datetime.strptime(dt_str, self.p.dtformat)

# Convert to internal format
        self.lines.datetime[0] = self.date2num(dt)

# Parse OHLCV
        self.lines.open[0] = float(linetokens[1])
        self.lines.high[0] = float(linetokens[2])
        self.lines.low[0] = float(linetokens[3])
        self.lines.close[0] = float(linetokens[4])
        self.lines.volume[0] = float(linetokens[5])
        self.lines.openinterest[0] = 0.0

        return True

```bash

### Creating a Custom Live Feed

```python
class MyLiveData(bt.DataBase):
    """Custom live data feed."""

    params = (('api_url', '<https://api.example.com'),)>

    def __init__(self):
        super().__init__()
        self.api_url = self.p.api_url

    def start(self):
        super().start()

# Connect to data source
        self.connected = True
        self.put_notification(self.CONNECTED)

    def stop(self):

# Disconnect
        self.connected = False
        super().stop()

    def _load(self):

# Fetch next bar from API
        try:
            import requests
            response = requests.get(self.api_url)
            bar_data = response.json()

# Parse and set data
            dt = datetime.fromtimestamp(bar_data['timestamp'])
            self.lines.datetime[0] = self.date2num(dt)
            self.lines.open[0] = bar_data['open']
            self.lines.high[0] = bar_data['high']
            self.lines.low[0] = bar_data['low']
            self.lines.close[0] = bar_data['close']
            self.lines.volume[0] = bar_data['volume']

            return True
        except Exception:
            self.put_notification(self.DISCONNECTED)
            return False

    def islive(self):
        return True

```bash

### Creating a Feed with Custom Lines

```python
class ExtendedData(bt.feeds.PandasData):
    """Data feed with additional lines."""

# Add custom lines
    lines = ('adj_close', 'dividend',)

# Map to DataFrame columns
    params = (
        ('adj_close', -1),
        ('dividend', -1),
    )

```bash

## Working with Multiple Data Feeds

### Adding Multiple Feeds

```python

# Add multiple data feeds

cerebro.adddata(bt.feeds.PandasData(dataname=df_aapl), name='AAPL')
cerebro.adddata(bt.feeds.PandasData(dataname=df_msft), name='MSFT')
cerebro.adddata(bt.feeds.PandasData(dataname=df_goog), name='GOOGL')

class MyStrategy(bt.Strategy):
    def __init__(self):
        self.aapl = self.getdatabyname('AAPL')
        self.msft = self.getdatabyname('MSFT')
        self.goog = self.getdatabyname('GOOGL')

    def next(self):

# Access different feeds
        if self.aapl.close[0] > self.msft.close[0]:
            self.buy(data=self.aapl)

```bash

### Data Feed Synchronization

```python

# Master/slave relationship

data_daily = bt.feeds.PandasData(dataname=daily_df, name='daily')
data_hourly = bt.feeds.PandasData(dataname=hourly_df, name='hourly')

# Hourly data will be synchronized to daily boundaries

cerebro.adddata(data_daily)
cerebro.adddata(data_hourly)

```bash

## Performance Tips

### Preloading

```python

# For faster backtesting with historical data

cerebro.run(preload=True)

```bash

### Memory Management

```python

# Limit memory usage for large datasets

data = bt.feeds.PandasData(dataname=large_df)
cerebro.adddata(data)
data.qbuffer(savemem=1000)  # Keep only 1000 bars in memory

```bash

### No Caching

```python

# Disable optimization for small datasets

cerebro.run preload=True, runonce=True, exactbars=False

```bash

## Complete Examples

### Example 1: CSV Backtest

```python
import backtrader as bt
from datetime import datetime

class SmaCross(bt.Strategy):
    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=10)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=30)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)

    def next(self):
        if self.crossover > 0:
            self.buy()
        elif self.crossover < 0:
            self.sell()

# Create cerebro

cerebro = bt.Cerebro()

# Add CSV data

data = bt.feeds.GenericCSVData(
    dataname='stock_data.csv',
    datetime=0,
    time=-1,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    dtformat='%Y-%m-%d',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31),
)
cerebro.adddata(data)

# Add strategy

cerebro.addstrategy(SmaCross)

# Run

results = cerebro.run()

```bash

### Example 2: Pandas DataFrame

```python
import backtrader as bt
import pandas as pd

# Load data

df = pd.read_csv('data.csv', parse_dates=['date'], index_col='date')

# Create data feed

data = bt.feeds.PandasData(
    dataname=df,
    datetime=None,  # Use index
    open='open',
    high='high',
    low='low',
    close='close',
    volume='volume',
)

# Create cerebro and add data

cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.run()

```bash

### Example 3: Resampling

```python
import backtrader as bt

# Load minute data

data = bt.feeds.GenericCSVData(dataname='minute_data.csv')

# Create cerebro

cerebro = bt.Cerebro()

# Add resampled data (hourly)

cerebro.resampledata(
    data,
    timeframe=bt.TimeFrame.Minutes,
    compression=60,
    bar2edge=True,
    rightedge=True,
)

# Add original data for comparison

cerebro.adddata(data, name='minutes')

# Run

cerebro.run()

```bash

### Example 4: Multiple Feeds

```python
import backtrader as bt

class MultiAssetStrategy(bt.Strategy):
    def __init__(self):

# Store data feeds
        self.data1 = self.datas[0]
        self.data2 = self.datas[1]

# Create indicators for each
        self.sma1 = bt.indicators.SMA(self.data1.close, period=20)
        self.sma2 = bt.indicators.SMA(self.data2.close, period=20)

    def next(self):

# Trade based on both feeds
        if self.sma1[0] > self.sma2[0]:
            if not self.getposition(self.data1):
                self.buy(data=self.data1)

cerebro = bt.Cerebro()

# Add multiple data feeds

cerebro.adddata(bt.feeds.PandasData(dataname=df1), name='Asset1')
cerebro.adddata(bt.feeds.PandasData(dataname=df2), name='Asset2')

cerebro.addstrategy(MultiAssetStrategy)
cerebro.run()

```bash

## Next Steps

- [Strategy API](strategy.md) - Strategy development
- [Indicator API](indicator.md) - Technical indicators
- [Cerebro API](cerebro.md) - Backtesting engine
