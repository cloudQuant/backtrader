- --

title: Data Feeds
description: Loading data from various sources

- --

# Data Feeds

Data feeds provide market data to your strategies. Backtrader supports multiple data sources and formats.

## Quick Start

```python
import backtrader as bt
import datetime

# Add data to cerebro

data = bt.feeds.CSVGeneric(
    dataname='AAPL.csv',
    datetime=0,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    dtformat='%Y-%m-%d'
)

cerebro = bt.Cerebro()
cerebro.adddata(data)

```bash

## Data Sources

### CSV Files

#### Generic CSV

```python
data = bt.feeds.CSVGeneric(
    dataname='data.csv',
    datetime=0,     # Column index for datetime
    time=-1,        # Column index for time (optional)
    open=1,         # Column index for open price
    high=2,         # Column index for high price
    low=3,          # Column index for low price
    close=4,        # Column index for close price
    volume=5,       # Column index for volume
    openinterest=-1,# Column index for open interest (optional)
    dtformat='%Y-%m-%d %H:%M:%S',
    tmformat='%H:%M:%S',
    timeframe=bt.TimeFrame.Days
)

```bash

#### BTC CSV (Bitcoin specific)

```python
data = bt.feeds.BTCCSV(
    dataname='btc.csv',
    datetime=None,  # Auto-detect
    timeframe=bt.TimeFrame.Minutes
)

```bash

### Pandas DataFrame

```python
import pandas as pd

# Create DataFrame

df = pd.DataFrame({
    'datetime': pd.date_range('2023-01-01', periods=100),
    'open': np.random.randn(100).cumsum() + 100,
    'high': np.random.randn(100).cumsum() + 102,
    'low': np.random.randn(100).cumsum() + 98,
    'close': np.random.randn(100).cumsum() + 100,
    'volume': np.random.randint(1000, 10000, 100)
})

# Convert to data feed

data = bt.feeds.PandasData(
    dataname=df,
    datetime=None,  # Use index as datetime
    open='open',
    high='high',
    low='low',
    close='close',
    volume='volume',
    openinterest=None
)

```bash

### Yahoo Finance

```python
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime.datetime(2023, 1, 1),
    todate=datetime.datetime(2023, 12, 31),
    timeframe=bt.TimeFrame.Days,
    adjclose=False,  # Use adjusted close
    reversed=False   # Data order

)

```bash

### Live Trading Data

#### CCXT (Cryptocurrency)

```python
from backtrader.feeds import CCXTFeed

# Create store

store = CCXTStore(
    exchange='binance',
    currency='USDT',
    config={'apiKey': 'YOUR_KEY', 'secret': 'YOUR_SECRET'}
)

# Add data feed

data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    use_websocket=True  # Use WebSocket for live data

)

cerebro.adddata(data)
cerebro.setbroker(store.getbroker())

```bash

#### CTP (Futures)

```python
from backtrader.stores import CTPStore
from backtrader.feeds import CTPData

# Create store

store = CTPStore(
    userid='YOUR_ID',
    password='YOUR_PASSWORD',
    brokerid='9999',  # SimNow
    appid='simnow_client',
    authcode='0000000000000000'
)

# Add data feed

data = CTPData(
    store=store,
    dataname='au2506',  # Contract
    timeframe=bt.TimeFrame.Minutes
)

cerebro.adddata(data)
cerebro.setbroker(store.getbroker())

```bash

## Multiple Data Feeds

```python
cerebro = bt.Cerebro()

# Add multiple data feeds

data1 = bt.feeds.YahooFinanceData(dataname='AAPL', ...)
data2 = bt.feeds.YahooFinanceData(dataname='MSFT', ...)
data3 = bt.feeds.YahooFinanceData(dataname='GOOGL', ...)

cerebro.adddata(data1, name='AAPL')
cerebro.adddata(data2, name='MSFT')
cerebro.adddata(data3, name='GOOGL')

# Access in strategy

class MyStrategy(bt.Strategy):
    def next(self):
        aapl_price = self.datas[0].close[0]
        msft_price = self.datas[1].close[0]  # or self.msft.close[0]
        googl_price = self.datas[2].close[0]  # or self.googl.close[0]

```bash

## Data Resampling

Convert data to a different timeframe.

```python

# Original data is minute-based

data = bt.feeds.CSVGeneric(dataname='minute_data.csv', ...)

# Resample to daily

cerebro = bt.Cerebro()
cerebro.resampledata(data, timeframe=bt.TimeFrame.Days)
cerebro.adddata(data, name='daily')

```bash

## Data Filtering

### Calendar Days Filter

```python

# Only trade on specific days

data = bt.feeds.CSVGeneric(dataname='data.csv', ...)
data.addfilter(bt.filters.CalendarDays())

```bash

### Session Filter

```python

# Only trade during regular hours

data = bt.feeds.CSVGeneric(dataname='data.csv', ...)
data.addfilter(bt.filters.SessionFilter(
    starttime=datetime.time(9, 30),
    endtime=datetime.time(16, 0)
))

```bash

## Data Requirements

### Minimum Data Format

Each data feed requires at minimum:

| Field | Required | Description |

|-------|----------|-------------|

| datetime | Yes | Bar timestamp |

| open | Yes | Opening price |

| high | Yes | Highest price |

| low | Yes | Lowest price |

| close | Yes | Closing price |

| volume | No | Trading volume |

| openinterest | No | Open interest (futures) |

### CSV Format Example

```csv
datetime,open,high,low,close,volume
2023-01-01,100.0,102.5,99.5,101.0,1000000
2023-01-02,101.0,103.0,100.5,102.5,1200000
2023-01-03,102.5,104.0,102.0,103.0,900000

```bash

## Next Steps

- [Indicators](indicators.md) - Use indicators with your data
- [Strategies](strategies.md) - Build trading strategies
- [Live Trading](../live-trading/ccxt-guide.md) - Real-time trading
