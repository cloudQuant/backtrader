- --

title: Data Acquisition Guide
description: Comprehensive guide for acquiring, cleaning, and storing market data for Backtrader

- --

# Data Acquisition Guide

Reliable data is the foundation of successful backtesting. This guide covers everything you need to know about acquiring, cleaning, storing, and validating market data for Backtrader.

## Quick Start

### Basic CSV Loading

```python
import backtrader as bt

# Load data from CSV file

data = bt.feeds.GenericCSVData(
    dataname='data.csv',
    datetime=0,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    fromdate=datetime(2023, 1, 1),
    todate=datetime(2023, 12, 31)
)

cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.run()

```bash

### Pandas DataFrame Loading

```python
import pandas as pd
import backtrader as bt

# Load data using pandas

df = pd.read_csv('data.csv', parse_dates=['datetime'], index_col='datetime')

# Create data feed

data = bt.feeds.PandasData(dataname=df)

cerebro.adddata(data)

```bash

## Exchange Data Interfaces

### Traditional Market Data

#### Yahoo Finance

```python
import backtrader as bt
from datetime import datetime

# Yahoo Finance data feed

data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31),
    buffered=True
)

cerebro.adddata(data)

```bash

#### Interactive Brokers

```python

# Requires ibpy installation

data = bt.feeds.IBData(
    dataname='AAPL-STK-SMART',
    fromdate=datetime(2023, 1, 1),
    todate=datetime(2023, 12, 31),
    historical=True
)

```bash

#### OANDA

```python

# OANDA data feed

store = bt.stores.OandaStore(
    token='your_token',
    account='your_account_id',
    practice=True  # Use practice account

)

data = store.getdata(
    dataname='EUR_USD',
    timeframe=bt.TimeFrame.Minutes,
    compression=15
)

```bash

#### Quandl

```python

# Quandl data feed

data = bt.feeds.QuandlData(
    dataname='WIKI/AAPL',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31)
)

```bash

### Database Data Sources

#### InfluxDB

```python

# InfluxDB data feed for time-series data

data = bt.feeds.InfluxDB(
    dataname='market_data',
    host='localhost',
    port=8086,
    username='user',
    password='password',
    database='crypto',
    measurement='btc_usdt',
    timeframe=bt.TimeFrame.Minutes
)

```bash

## Data Cleaning and Preprocessing

### Handling Missing Data

```python
import pandas as pd
import numpy as np

def clean_ohlcv_data(df):
    """Clean OHLCV data for backtesting."""

# Remove duplicates
    df = df.drop_duplicates(subset=['datetime'])

# Forward fill missing values (optional)
    df = df.ffill()

# Handle outliers - remove bars with unrealistic values
    df = df[
        (df['high'] >= df['low']) &
        (df['high'] >= df['open']) &
        (df['high'] >= df['close']) &
        (df['low'] <= df['open']) &
        (df['low'] <= df['close']) &
        (df['volume'] >= 0)
    ]

# Remove zero prices
    df = df[(df['close'] > 0) & (df['open'] > 0)]

    return df

# Usage

df = pd.read_csv('raw_data.csv', parse_dates=['datetime'])
df_clean = clean_ohlcv_data(df)

```bash

### Timezone Handling

```python
import pandas as pd

def standardize_timezone(df, timezone='UTC'):
    """Standardize timezone for market data."""

# Ensure datetime is timezone-aware
    if df.index.tz is None:
        df.index = df.index.tz_localize(timezone)
    else:
        df.index = df.index.tz_convert(timezone)

    return df

# Usage

df = pd.read_csv('data.csv', parse_dates=['datetime'], index_col='datetime')
df = standardize_timezone(df, 'UTC')

```bash

### Resampling Data

```python
def resample_data(df, timeframe='15T'):
    """
    Resample OHLCV data to different timeframe.

    Timeframes:

    - '1T', '5T', '15T', '30T' for minutes
    - '1H', '4H' for hours
    - '1D' for daily

    """

# Resample with proper aggregation
    df_resampled = df.resample(timeframe).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()

    return df_resampled

# Usage: Resample tick data to 15-minute bars

df_15m = resample_data(df_tick, '15T')

```bash

### Outlier Detection

```python
def detect_outliers(df, window=20, threshold=3):
    """Detect price outliers using z-score."""
    df = df.copy()

# Calculate z-score for closing prices
    df['z_score'] = (
        (df['close'] - df['close'].rolling(window).mean()) /
        df['close'].rolling(window).std()
    )

# Flag outliers
    outliers = df[np.abs(df['z_score']) > threshold]

    return outliers

# Usage

outliers = detect_outliers(df)
print(f"Found {len(outliers)} outliers")

# Option 1: Remove outliers

df_clean = df[np.abs(df['z_score']) <= 3]

# Option 2: Cap outliers to threshold

df_capped = df.copy()
df_capped['close'] = np.where(
    np.abs(df['z_score']) > 3,
    df['close'].rolling(20).mean(),
    df['close']
)

```bash

## Data Storage Solutions

### CSV Format

- *Pros**: Simple, human-readable, universal compatibility
- *Cons**: Slow for large datasets, no compression

```python
import pandas as pd

# Save to CSV

df.to_csv('market_data.csv', index=True)

# Load from CSV

df = pd.read_csv('market_data.csv', parse_dates=['datetime'], index_col='datetime')

```bash

### Parquet Format

- *Pros**: Fast I/O, excellent compression, columnar storage
- *Cons**: Binary format (not human-readable)

```python
import pandas as pd

# Save to Parquet (recommended for large datasets)

df.to_parquet('market_data.parquet', compression='snappy')

# Load from Parquet

df = pd.read_parquet('market_data.parquet')

# Backtrader usage

data = bt.feeds.PandasData(dataname=df)

```bash

### HDF5 Format

- *Pros**: Fast read/write, hierarchical storage, good for time-series
- *Cons**: Requires PyTables, not as widely supported

```python
import pandas as pd

# Save to HDF5

df.to_hdf('market_data.h5', key='data', mode='w')

# Load from HDF5

df = pd.read_hdf('market_data.h5', key='data')

# Appending to existing file

df_new.to_hdf('market_data.h5', key='data', mode='a', append=True, format='table')

```bash

### Database Storage

#### SQLite (Local)

```python
import sqlite3
import pandas as pd

# Save to SQLite

conn = sqlite3.connect('market_data.db')
df.to_sql('ohlcv', conn, if_exists='replace', index=True)

# Load from SQLite

df = pd.read_sql('SELECT *FROM ohlcv', conn, parse_dates=['datetime'], index_col='datetime')
conn.close()

```bash

#### PostgreSQL (Production)

```python
import psycopg2
from sqlalchemy import create_engine

# Save to PostgreSQL

engine = create_engine('postgresql://user:password@localhost/market_db')
df.to_sql('ohlcv', engine, if_exists='append', index=True)

# Load from PostgreSQL

df = pd.read_sql('SELECT*FROM ohlcv WHERE symbol = "BTC/USDT"', engine, parse_dates=['datetime'], index_col='datetime')

```bash

#### TimescaleDB (Time-series optimized)

```python

# TimescaleDB is PostgreSQL with time-series extensions

engine = create_engine('postgresql://user:password@localhost/timeseries_db')

# Create hypertable for optimal time-series performance

# (run once during setup)

with engine.connect() as conn:
    conn.execute("SELECT create_hypertable('ohlcv', 'datetime');")

# Normal PostgreSQL operations work

df.to_sql('ohlcv', engine, if_exists='append', index=True)

```bash

## Historical Data Backfill

### Fetching Historical Data

```python
import backtrader as bt
from datetime import datetime, timedelta

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT'
)

# Fetch historical data in chunks

def fetch_historical_data(symbol, start_date, end_date, timeframe='15m'):
    """Fetch historical data in chunks to handle API limits."""
    data = store.getdata(
        dataname=symbol,
        timeframe=bt.TimeFrame.Minutes,
        compression=15,  # 15-minute bars
        fromdate=start_date,
        todate=end_date,
        ohlcv_limit=1000,  # Bars per request
        historical=True
    )

# Convert to DataFrame for storage
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.run()

    return data

# Usage

start = datetime(2023, 1, 1)
end = datetime(2023, 12, 31)

data = fetch_historical_data('BTC/USDT', start, end)

```bash

### Backfill with Storage

```python
def backfill_and_store(symbol, start_date, end_date, storage_path):
    """Fetch historical data and store to file."""
    import pandas as pd

# Fetch data
    store = bt.stores.CCXTStore(exchange='binance', currency='USDT')
    data = store.getdata(
        dataname=symbol,
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
        fromdate=start_date,
        todate=end_date,
        historical=True
    )

# Run cerebro to load data
    cerebro = bt.Cerebro()
    cerebro.adddata(data)

# Extract data and save

# (This depends on your specific implementation)

# data_df = extract_dataframe(data)

# data_df.to_parquet(storage_path)

    print(f"Backfilled {symbol} to {storage_path}")

# Usage

backfill_and_store(
    'BTC/USDT',
    datetime(2020, 1, 1),
    datetime.now(),
    'data/btc_usdt_15m.parquet'
)

```bash

## Data Quality Validation

### Validation Checklist

```python
def validate_ohlcv_data(df):
    """Comprehensive OHLCV data validation."""
    issues = []

# 1. Check for missing values
    missing = df.isnull().sum()
    if missing.any():
        issues.append(f"Missing values: {missing[missing > 0].to_dict()}")

# 2. Check for duplicate timestamps
    duplicates = df.index.duplicated()
    if duplicates.sum() > 0:
        issues.append(f"Duplicate timestamps: {duplicates.sum()} found")

# 3. Check OHLC relationships
    invalid_ohlc = (
        (df['high'] < df['low']) |

        (df['high'] < df['open']) |

        (df['high'] < df['close']) |

        (df['low'] > df['open']) |

        (df['low'] > df['close'])
    )
    if invalid_ohlc.sum() > 0:
        issues.append(f"Invalid OHLC relationships: {invalid_ohlc.sum()} bars")

# 4. Check for negative values
    negative = (df[['open', 'high', 'low', 'close', 'volume']] < 0).any()
    if negative.any():
        issues.append(f"Negative values: {negative[negative].index.tolist()}")

# 5. Check for zero prices
    zero_prices = (df['close'] == 0).sum()
    if zero_prices > 0:
        issues.append(f"Zero close prices: {zero_prices} bars")

# 6. Check time sequence
    not_monotonic = not df.index.is_monotonic_increasing
    if not_monotonic:
        issues.append("Timestamps not monotonically increasing")

# 7. Check for outliers (extreme price changes)
    price_change = df['close'].pct_change().abs()
    extreme_changes = price_change > 0.5  # More than 50% change
    if extreme_changes.sum() > 0:
        issues.append(f"Extreme price changes: {extreme_changes.sum()} bars")

    return issues

# Usage

df = pd.read_parquet('market_data.parquet')
issues = validate_ohlcv_data(df)

if issues:
    print("Data validation issues found:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("Data validation passed!")

```bash

### Statistical Summary

```python
def data_quality_report(df):
    """Generate a comprehensive data quality report."""
    report = {
        'total_bars': len(df),
        'date_range': f"{df.index.min()} to {df.index.max()}",
        'missing_values': df.isnull().sum().to_dict(),
        'duplicate_bars': df.index.duplicated().sum(),
        'price_stats': {
            'min_close': df['close'].min(),
            'max_close': df['close'].max(),
            'mean_close': df['close'].mean(),
            'std_close': df['close'].std()
        },
        'volume_stats': {
            'min_volume': df['volume'].min(),
            'max_volume': df['volume'].max(),
            'mean_volume': df['volume'].mean()
        },
        'gaps': detect_time_gaps(df)
    }

    return report

def detect_time_gaps(df, expected_freq='15T'):
    """Detect time gaps in the data."""
    expected_delta = pd.Timedelta(expected_freq)
    actual_deltas = df.index.to_series().diff()
    gaps = actual_deltas[actual_deltas > expected_delta * 1.5]

    return len(gaps)

# Usage

report = data_quality_report(df)
import json
print(json.dumps(report, indent=2, default=str))

```bash

## Complete Examples

### Example 1: Data Pipeline

```python
import pandas as pd
import backtrader as bt
from datetime import datetime, timedelta

class DataPipeline:
    """Complete data pipeline for Backtrader."""

    def __init__(self, storage_path='./data'):
        self.storage_path = storage_path

    def fetch(self, exchange, symbol, start, end, timeframe='15m'):
        """Fetch data from exchange."""
        store = bt.stores.CCXTStore(exchange=exchange, currency='USDT')
        compression = int(timeframe[:-1])

        data = store.getdata(
            dataname=symbol,
            timeframe=bt.TimeFrame.Minutes,
            compression=compression,
            fromdate=start,
            todate=end,
            historical=True,
            ohlcv_limit=1000
        )

        return data

    def clean(self, df):
        """Clean and validate data."""

# Remove duplicates
        df = df[~df.index.duplicated(keep='first')]

# Validate OHLC
        df = df[
            (df['high'] >= df['low']) &
            (df['high'] >= df['open']) &
            (df['high'] >= df['close']) &
            (df['low'] <= df['open']) &
            (df['low'] <= df['close']) &
            (df['volume'] >= 0)
        ]

# Forward fill small gaps
        df = df.ffill(limit=3)

        return df

    def store(self, df, symbol, timeframe):
        """Store data efficiently."""
        filename = f"{self.storage_path}/{symbol.replace('/', '_')}_{timeframe}.parquet"
        df.to_parquet(filename, compression='snappy')
        print(f"Stored data to {filename}")
        return filename

    def load(self, symbol, timeframe):
        """Load stored data."""
        filename = f"{self.storage_path}/{symbol.replace('/', '_')}_{timeframe}.parquet"
        df = pd.read_parquet(filename)
        return df

    def create_feed(self, df):
        """Create Backtrader data feed."""
        return bt.feeds.PandasData(dataname=df)

# Usage

pipeline = DataPipeline()

# Fetch and store

start_date = datetime(2023, 1, 1)
end_date = datetime.now()

data = pipeline.fetch('binance', 'BTC/USDT', start_date, end_date)

# ... convert data to DataFrame ...

df = convert_to_dataframe(data)
df_clean = pipeline.clean(df)
pipeline.store(df_clean, 'BTC/USDT', '15m')

# Load and create feed

df_loaded = pipeline.load('BTC/USDT', '15m')
feed = pipeline.create_feed(df_loaded)

```bash

### Example 3: Multi-Source Data Aggregator

```python
class MultiSourceAggregator:
    """Aggregate data from multiple sources."""

    def __init__(self):
        self.sources = []

    def add_csv_source(self, path, symbol):
        """Add CSV data source."""
        df = pd.read_csv(path, parse_dates=['datetime'], index_col='datetime')
        self.sources.append({'symbol': symbol, 'data': df, 'type': 'csv'})
        return self

    def add_exchange_source(self, exchange, symbol, start, end):
        """Add exchange data source."""
        store = bt.stores.CCXTStore(exchange=exchange, currency='USDT')
        data = store.getdata(
            dataname=symbol,
            timeframe=bt.TimeFrame.Minutes,
            compression=15,
            fromdate=start,
            todate=end,
            historical=True
        )
        self.sources.append({'symbol': symbol, 'data': data, 'type': 'exchange'})
        return self

    def normalize(self):
        """Normalize all data sources to common format."""
        normalized = []
        for source in self.sources:
            if source['type'] == 'csv':
                df = source['data']
            else:

# Convert exchange data to DataFrame
                df = self._exchange_to_df(source['data'])

# Apply standard resampling
            df = self._resample_to_common(df, '15T')
            normalized.append({'symbol': source['symbol'], 'data': df})

        return normalized

    def merge(self, normalized_data):
        """Merge multiple data sources."""
        merged = pd.DataFrame()
        for item in normalized_data:
            if merged.empty:
                merged = item['data'].copy()
            else:
                merged = merged.join(item['data'], how='outer', rsuffix=f"_{item['symbol']}")

        return merged

# Usage

aggregator = MultiSourceAggregator()
aggregator.add_csv_source('data/BTC.csv', 'BTC')
aggregator.add_exchange_source('binance', 'ETH/USDT', datetime(2023, 1, 1), datetime.now())

normalized = aggregator.normalize()
merged = aggregator.merge(normalized)

```bash

## Best Practices

### Data Sourcing

1. **Use multiple data sources**for critical data to verify accuracy

2.**Check data frequency**matches your strategy requirements
3.**Consider survivorship bias**when using stock data
4.**Include dividend and split adjustments**for equity data

### Data Storage

1.**Use Parquet format**for large datasets (best performance/compression ratio)
2.**Organize by symbol and timeframe**in directory structure
3.**Keep raw data separate**from processed data
4.**Version your datasets**for reproducibility

### Real-time Data

1.**Always implement reconnection logic**for live feeds
2.**Use WebSocket**for lower latency when available
3.**Backfill missing bars**on reconnection
4.**Monitor data quality**in real-time

### Data Validation

1.**Validate before backtesting**- catch issues early
2.**Log data quality metrics**for each backtest
3.**Set up alerts**for unusual data patterns
4.**Document known data issues** (e.g., exchange downtime)

## Troubleshooting

### Common Issues

| Issue | Solution |

|-------|----------|

| Data gaps in series | Use `ffill()` or detect and mark gap periods |

| Duplicate timestamps | `df.drop_duplicates(subset=['datetime'])` |

| Wrong timezone | Standardize all data to UTC |

| Memory errors | Use `qbuffer()` or process in chunks |

| Slow loading | Convert CSV to Parquet format |

| Missing bars | Implement backfill logic |

| Invalid OHLC | Validate and filter/correct |

## Next Steps

- [Performance Optimization](performance-optimization.md) - Speed up your backtests
- [TS Mode Guide](ts-mode.md) - Time series optimization for large datasets
- [Live Trading Guide](../CCXT_LIVE_TRADING_GUIDE.md) - Real trading with CCXT
