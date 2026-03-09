- --

title: 数据获取指南
description: Backtrader 数据获取、清洗、存储和验证的综合指南

- --

# 数据获取指南

可靠的数据是成功回测的基础。本指南全面介绍为 Backtrader 获取、清洗、存储和验证市场数据所需的所有知识。

## 快速开始

### 基础 CSV 加载

```python
import backtrader as bt

# 从 CSV 文件加载数据

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

### Pandas DataFrame 加载

```python
import pandas as pd
import backtrader as bt

# 使用 pandas 加载数据

df = pd.read_csv('data.csv', parse_dates=['datetime'], index_col='datetime')

# 创建数据源

data = bt.feeds.PandasData(dataname=df)

cerebro.adddata(data)

```bash

## 交易所数据接口

### 传统市场数据

#### Yahoo Finance

```python
import backtrader as bt
from datetime import datetime

# Yahoo Finance 数据源

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

# 需要 ibpy 安装

data = bt.feeds.IBData(
    dataname='AAPL-STK-SMART',
    fromdate=datetime(2023, 1, 1),
    todate=datetime(2023, 12, 31),
    historical=True
)

```bash

#### OANDA 外汇

```python

# OANDA 数据源

store = bt.stores.OandaStore(
    token='your_token',
    account='your_account_id',
    practice=True  # 使用模拟账户

)

data = store.getdata(
    dataname='EUR_USD',
    timeframe=bt.TimeFrame.Minutes,
    compression=15
)

```bash

#### Quandl

```python

# Quandl 数据源

data = bt.feeds.QuandlData(
    dataname='WIKI/AAPL',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31)
)

```bash

### 数据库数据源

#### InfluxDB

```python

# InfluxDB 数据源用于时间序列数据

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

## 数据清洗和预处理

### 处理缺失数据

```python
import pandas as pd
import numpy as np

def clean_ohlcv_data(df):
    """清洗用于回测的 OHLCV 数据。"""

# 删除重复项
    df = df.drop_duplicates(subset=['datetime'])

# 前向填充缺失值（可选）
    df = df.ffill()

# 处理异常值 - 删除不现实的 K 线
    df = df[
        (df['high'] >= df['low']) &
        (df['high'] >= df['open']) &
        (df['high'] >= df['close']) &
        (df['low'] <= df['open']) &
        (df['low'] <= df['close']) &
        (df['volume'] >= 0)
    ]

# 删除零价格
    df = df[(df['close'] > 0) & (df['open'] > 0)]

    return df

# 使用方法

df = pd.read_csv('raw_data.csv', parse_dates=['datetime'])
df_clean = clean_ohlcv_data(df)

```bash

### 时区处理

```python
import pandas as pd

def standardize_timezone(df, timezone='UTC'):
    """标准化市场数据的时区。"""

# 确保 datetime 是时区感知的
    if df.index.tz is None:
        df.index = df.index.tz_localize(timezone)
    else:
        df.index = df.index.tz_convert(timezone)

    return df

# 使用方法

df = pd.read_csv('data.csv', parse_dates=['datetime'], index_col='datetime')
df = standardize_timezone(df, 'UTC')

```bash

### 数据重采样

```python
def resample_data(df, timeframe='15T'):
    """
    将 OHLCV 数据重采样到不同的时间周期。

    时间周期:

    - '1T', '5T', '15T', '30T' 表示分钟
    - '1H', '4H' 表示小时
    - '1D' 表示日线

    """

# 使用适当的聚合进行重采样
    df_resampled = df.resample(timeframe).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()

    return df_resampled

# 使用方法: 将 tick 数据重采样为 15 分钟 K 线

df_15m = resample_data(df_tick, '15T')

```bash

### 异常值检测

```python
def detect_outliers(df, window=20, threshold=3):
    """使用 z-score 检测价格异常值。"""
    df = df.copy()

# 计算收盘价的 z-score
    df['z_score'] = (
        (df['close'] - df['close'].rolling(window).mean()) /
        df['close'].rolling(window).std()
    )

# 标记异常值
    outliers = df[np.abs(df['z_score']) > threshold]

    return outliers

# 使用方法

outliers = detect_outliers(df)
print(f"发现 {len(outliers)} 个异常值")

# 选项 1: 删除异常值

df_clean = df[np.abs(df['z_score']) <= 3]

# 选项 2: 将异常值限制在阈值内

df_capped = df.copy()
df_capped['close'] = np.where(
    np.abs(df['z_score']) > 3,
    df['close'].rolling(20).mean(),
    df['close']
)

```bash

## 数据存储方案

### CSV 格式

- *优点**: 简单、人类可读、通用兼容性好
- *缺点**: 大数据集加载慢、无压缩

```python
import pandas as pd

# 保存为 CSV

df.to_csv('market_data.csv', index=True)

# 从 CSV 加载

df = pd.read_csv('market_data.csv', parse_dates=['datetime'], index_col='datetime')

```bash

### Parquet 格式

- *优点**: 快速 I/O、优秀压缩、列式存储
- *缺点**: 二进制格式（不可读）

```python
import pandas as pd

# 保存为 Parquet（推荐用于大数据集）

df.to_parquet('market_data.parquet', compression='snappy')

# 从 Parquet 加载

df = pd.read_parquet('market_data.parquet')

# Backtrader 使用

data = bt.feeds.PandasData(dataname=df)

```bash

### HDF5 格式

- *优点**: 快速读写、分层存储、适合时间序列
- *缺点**: 需要 PyTables、支持度不如 Parquet

```python
import pandas as pd

# 保存为 HDF5

df.to_hdf('market_data.h5', key='data', mode='w')

# 从 HDF5 加载

df = pd.read_hdf('market_data.h5', key='data')

# 追加到现有文件

df_new.to_hdf('market_data.h5', key='data', mode='a', append=True, format='table')

```bash

### 数据库存储

#### SQLite (本地)

```python
import sqlite3
import pandas as pd

# 保存到 SQLite

conn = sqlite3.connect('market_data.db')
df.to_sql('ohlcv', conn, if_exists='replace', index=True)

# 从 SQLite 加载

df = pd.read_sql('SELECT *FROM ohlcv', conn, parse_dates=['datetime'], index_col='datetime')
conn.close()

```bash

#### PostgreSQL (生产环境)

```python
import psycopg2
from sqlalchemy import create_engine

# 保存到 PostgreSQL

engine = create_engine('postgresql://user:password@localhost/market_db')
df.to_sql('ohlcv', engine, if_exists='append', index=True)

# 从 PostgreSQL 加载

df = pd.read_sql(
    'SELECT*FROM ohlcv WHERE symbol = "BTC/USDT"',
    engine,
    parse_dates=['datetime'],
    index_col='datetime'
)

```bash

#### TimescaleDB (时间序列优化)

```python

# TimescaleDB 是带时间序列扩展的 PostgreSQL

engine = create_engine('postgresql://user:password@localhost/timeseries_db')

# 创建超表以获得最佳时间序列性能

# （在设置时运行一次）

with engine.connect() as conn:
    conn.execute("SELECT create_hypertable('ohlcv', 'datetime');")

# 正常 PostgreSQL 操作即可

df.to_sql('ohlcv', engine, if_exists='append', index=True)

```bash

## 历史数据回补

### 获取历史数据

```python
import backtrader as bt
from datetime import datetime, timedelta

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT'
)

# 分块获取历史数据

def fetch_historical_data(symbol, start_date, end_date, timeframe='15m'):
    """分块获取历史数据以处理 API 限制。"""
    data = store.getdata(
        dataname=symbol,
        timeframe=bt.TimeFrame.Minutes,
        compression=15,  # 15 分钟 K 线
        fromdate=start_date,
        todate=end_date,
        ohlcv_limit=1000,  # 每次请求的 K 线数
        historical=True
    )

# 转换为 DataFrame 进行存储
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.run()

    return data

# 使用方法

start = datetime(2023, 1, 1)
end = datetime(2023, 12, 31)

data = fetch_historical_data('BTC/USDT', start, end)

```bash

### 带存储的回补

```python
def backfill_and_store(symbol, start_date, end_date, storage_path):
    """获取历史数据并存储到文件。"""
    import pandas as pd

# 获取数据
    store = bt.stores.CCXTStore(exchange='binance', currency='USDT')
    data = store.getdata(
        dataname=symbol,
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
        fromdate=start_date,
        todate=end_date,
        historical=True
    )

# 运行 cerebro 加载数据
    cerebro = bt.Cerebro()
    cerebro.adddata(data)

# 提取数据并保存

# （这取决于您的具体实现）

# data_df = extract_dataframe(data)

# data_df.to_parquet(storage_path)

    print(f"已回补 {symbol} 到 {storage_path}")

# 使用方法

backfill_and_store(
    'BTC/USDT',
    datetime(2020, 1, 1),
    datetime.now(),
    'data/btc_usdt_15m.parquet'
)

```bash

### 定时数据更新

```python
import schedule
import time

def update_daily():
    """每日数据更新任务。"""
    symbols = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT']
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1)

    for symbol in symbols:
        try:
            backfill_and_store(symbol, start_date, end_date, f'data/{symbol}_15m.parquet')
        except Exception as e:
            print(f"更新 {symbol} 失败: {e}")

# 每天凌晨 2 点更新

schedule.every().day.at("02:00").do(update_daily)

while True:
    schedule.run_pending()
    time.sleep(60)

```bash

## 数据质量验证

### 验证清单

```python
def validate_ohlcv_data(df):
    """全面的 OHLCV 数据验证。"""
    issues = []

# 1. 检查缺失值
    missing = df.isnull().sum()
    if missing.any():
        issues.append(f"缺失值: {missing[missing > 0].to_dict()}")

# 2. 检查重复时间戳
    duplicates = df.index.duplicated()
    if duplicates.sum() > 0:
        issues.append(f"重复时间戳: 发现 {duplicates.sum()} 个")

# 3. 检查 OHLC 关系
    invalid_ohlc = (
        (df['high'] < df['low']) |

        (df['high'] < df['open']) |

        (df['high'] < df['close']) |

        (df['low'] > df['open']) |

        (df['low'] > df['close'])
    )
    if invalid_ohlc.sum() > 0:
        issues.append(f"无效的 OHLC 关系: {invalid_ohlc.sum()} 根 K 线")

# 4. 检查负值
    negative = (df[['open', 'high', 'low', 'close', 'volume']] < 0).any()
    if negative.any():
        issues.append(f"负值: {negative[negative].index.tolist()}")

# 5. 检查零价格
    zero_prices = (df['close'] == 0).sum()
    if zero_prices > 0:
        issues.append(f"零收盘价: {zero_prices} 根 K 线")

# 6. 检查时间序列
    not_monotonic = not df.index.is_monotonic_increasing
    if not_monotonic:
        issues.append("时间戳非单调递增")

# 7. 检查异常值（极端价格变化）
    price_change = df['close'].pct_change().abs()
    extreme_changes = price_change > 0.5  # 超过 50% 变化
    if extreme_changes.sum() > 0:
        issues.append(f"极端价格变化: {extreme_changes.sum()} 根 K 线")

    return issues

# 使用方法

df = pd.read_parquet('market_data.parquet')
issues = validate_ohlcv_data(df)

if issues:
    print("发现数据验证问题:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("数据验证通过！")

```bash

### 统计摘要

```python
def data_quality_report(df):
    """生成全面的数据质量报告。"""
    report = {
        '总 K 线数': len(df),
        '日期范围': f"{df.index.min()} 至 {df.index.max()}",
        '缺失值': df.isnull().sum().to_dict(),
        '重复 K 线': df.index.duplicated().sum(),
        '价格统计': {
            '最低收盘价': df['close'].min(),
            '最高收盘价': df['close'].max(),
            '平均收盘价': df['close'].mean(),
            '收盘价标准差': df['close'].std()
        },
        '成交量统计': {
            '最小成交量': df['volume'].min(),
            '最大成交量': df['volume'].max(),
            '平均成交量': df['volume'].mean()
        },
        '数据缺口': detect_time_gaps(df)
    }

    return report

def detect_time_gaps(df, expected_freq='15T'):
    """检测数据中的时间缺口。"""
    expected_delta = pd.Timedelta(expected_freq)
    actual_deltas = df.index.to_series().diff()
    gaps = actual_deltas[actual_deltas > expected_delta * 1.5]

    return len(gaps)

# 使用方法

report = data_quality_report(df)
import json
print(json.dumps(report, indent=2, default=str, ensure_ascii=False))

```bash

## 完整示例

### 示例 1: 数据管道

```python
import pandas as pd
import backtrader as bt
from datetime import datetime, timedelta

class DataPipeline:
    """Backtrader 的完整数据管道。"""

    def __init__(self, storage_path='./data'):
        self.storage_path = storage_path

    def fetch(self, exchange, symbol, start, end, timeframe='15m'):
        """从交易所获取数据。"""
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
        """清洗和验证数据。"""

# 删除重复项
        df = df[~df.index.duplicated(keep='first')]

# 验证 OHLC
        df = df[
            (df['high'] >= df['low']) &
            (df['high'] >= df['open']) &
            (df['high'] >= df['close']) &
            (df['low'] <= df['open']) &
            (df['low'] <= df['close']) &
            (df['volume'] >= 0)
        ]

# 前向填充小缺口
        df = df.ffill(limit=3)

        return df

    def store(self, df, symbol, timeframe):
        """高效存储数据。"""
        filename = f"{self.storage_path}/{symbol.replace('/', '_')}_{timeframe}.parquet"
        df.to_parquet(filename, compression='snappy')
        print(f"数据已存储到 {filename}")
        return filename

    def load(self, symbol, timeframe):
        """加载已存储的数据。"""
        filename = f"{self.storage_path}/{symbol.replace('/', '_')}_{timeframe}.parquet"
        df = pd.read_parquet(filename)
        return df

    def create_feed(self, df):
        """创建 Backtrader 数据源。"""
        return bt.feeds.PandasData(dataname=df)

# 使用方法

pipeline = DataPipeline()

# 获取并存储

start_date = datetime(2023, 1, 1)
end_date = datetime.now()

data = pipeline.fetch('binance', 'BTC/USDT', start_date, end_date)

# ... 将数据转换为 DataFrame ...

df = convert_to_dataframe(data)
df_clean = pipeline.clean(df)
pipeline.store(df_clean, 'BTC/USDT', '15m')

# 加载并创建数据源

df_loaded = pipeline.load('BTC/USDT', '15m')
feed = pipeline.create_feed(df_loaded)

```bash

### 示例 3: 多源数据聚合器

```python
class MultiSourceAggregator:
    """聚合多个数据源。"""

    def __init__(self):
        self.sources = []

    def add_csv_source(self, path, symbol):
        """添加 CSV 数据源。"""
        df = pd.read_csv(path, parse_dates=['datetime'], index_col='datetime')
        self.sources.append({'symbol': symbol, 'data': df, 'type': 'csv'})
        return self

    def add_exchange_source(self, exchange, symbol, start, end):
        """添加交易所数据源。"""
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
        """将所有数据源标准化为通用格式。"""
        normalized = []
        for source in self.sources:
            if source['type'] == 'csv':
                df = source['data']
            else:

# 将交易所数据转换为 DataFrame
                df = self._exchange_to_df(source['data'])

# 应用标准重采样
            df = self._resample_to_common(df, '15T')
            normalized.append({'symbol': source['symbol'], 'data': df})

        return normalized

    def merge(self, normalized_data):
        """合并多个数据源。"""
        merged = pd.DataFrame()
        for item in normalized_data:
            if merged.empty:
                merged = item['data'].copy()
            else:
                merged = merged.join(item['data'], how='outer', rsuffix=f"_{item['symbol']}")

        return merged

# 使用方法

aggregator = MultiSourceAggregator()
aggregator.add_csv_source('data/BTC.csv', 'BTC')
aggregator.add_exchange_source('binance', 'ETH/USDT', datetime(2023, 1, 1), datetime.now())

normalized = aggregator.normalize()
merged = aggregator.merge(normalized)

```bash

### 示例 4: 多交易所数据对比

```python
def compare_exchange_data(symbols, exchanges):
    """对比不同交易所的数据。"""
    cerebro = bt.Cerebro()

    for exchange in exchanges:
        store = bt.stores.CCXTStore(exchange=exchange, currency='USDT')

        for symbol in symbols:
            try:
                data = store.getdata(
                    dataname=symbol,
                    timeframe=bt.TimeFrame.Minutes,
                    compression=15,
                    fromdate=datetime.now() - timedelta(days=1),
                    historical=True
                )
                cerebro.adddata(data, name=f"{exchange}_{symbol}")
            except Exception as e:
                print(f"无法从 {exchange} 获取 {symbol}: {e}")

    return cerebro

# 使用方法: 对比币安和 OKX 的 BTC 数据

cerebro = compare_exchange_data(['BTC/USDT'], ['binance', 'okx'])

```bash

## 最佳实践

### 数据获取

1. **使用多个数据源**验证关键数据的准确性

2.**检查数据频率**是否符合策略要求
3.**考虑幸存者偏差**使用股票数据时
4.**包含股息和拆股调整**对于股票数据

### 数据存储

1.**使用 Parquet 格式**处理大数据集（最佳性能/压缩比）
2.**按交易对和时间周期**组织目录结构
3.**原始数据与处理后数据**分开存储
4.**版本控制数据集**以确保可重现性

### 实时数据

1.**始终实现重连逻辑**用于实时数据源
2.**使用 WebSocket**在可用时降低延迟
3.**重连时回补缺失 K 线**

1. **实时监控数据质量**

### 数据验证

1. **回测前验证**尽早发现问题

2.**记录数据质量指标**用于每次回测
3.**设置异常数据模式警报**

1. **记录已知数据问题**（如交易所停机时间）

## 故障排除

### 常见问题

| 问题 | 解决方案 |

|-------|----------|

| 数据系列中的缺口 | 使用 `ffill()` 或检测并标记缺口周期 |

| 重复时间戳 | `df.drop_duplicates(subset=['datetime'])` |

| 错误时区 | 将所有数据标准化为 UTC |

| 内存错误 | 使用 `qbuffer()` 或分块处理 |

| 加载缓慢 | 将 CSV 转换为 Parquet 格式 |

| 缺失 K 线 | 实现回补逻辑 |

| 无效的 OHLC | 验证并过滤/修正 |

## 下一步学习

- [性能优化](performance-optimization_zh.md) - 加速您的回测
- [TS 模式指南](ts-mode_zh.md) - 大数据集的时间序列优化
