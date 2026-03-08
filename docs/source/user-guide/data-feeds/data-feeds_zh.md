---
title: 数据源
description: 从各种来源加载数据

---
# 数据源

数据源为您的策略提供市场数据。Backtrader 支持多种数据源和格式。

## 快速开始

```python
import backtrader as bt
import datetime

# 向 cerebro 添加数据

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

```

## 数据源

### CSV 文件

#### 通用 CSV

```python
data = bt.feeds.CSVGeneric(
    dataname='data.csv',
    datetime=0,     # 日期时间列索引
    time=-1,        # 时间列索引 (可选)
    open=1,         # 开盘价列索引
    high=2,         # 最高价列索引
    low=3,          # 最低价列索引
    close=4,        # 收盘价列索引
    volume=5,       # 成交量列索引
    openinterest=-1,# 持仓量列索引 (可选)
    dtformat='%Y-%m-%d %H:%M:%S',
    tmformat='%H:%M:%S',
    timeframe=bt.TimeFrame.Days
)

```

#### BTC CSV (比特币专用)

```python
data = bt.feeds.BTCCSV(
    dataname='btc.csv',
    datetime=None,  # 自动检测
    timeframe=bt.TimeFrame.Minutes
)

```

### Pandas DataFrame

```python
import pandas as pd

# 创建 DataFrame

df = pd.DataFrame({
    'datetime': pd.date_range('2023-01-01', periods=100),
    'open': np.random.randn(100).cumsum() + 100,
    'high': np.random.randn(100).cumsum() + 102,
    'low': np.random.randn(100).cumsum() + 98,
    'close': np.random.randn(100).cumsum() + 100,
    'volume': np.random.randint(1000, 10000, 100)
})

# 转换为数据源

data = bt.feeds.PandasData(
    dataname=df,
    datetime=None,  # 使用索引作为日期时间
    open='open',
    high='high',
    low='low',
    close='close',
    volume='volume',
    openinterest=None
)

```

### Yahoo Finance

```python
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime.datetime(2023, 1, 1),
    todate=datetime.datetime(2023, 12, 31),
    timeframe=bt.TimeFrame.Days,
    adjclose=False,  # 使用复权收盘价
    reversed=False   # 数据顺序

)

```

### 实盘交易数据

#### CCXT (加密货币)

```python
from backtrader.feeds import CCXTFeed

# 创建存储

store = CCXTStore(
    exchange='binance',
    currency='USDT',
    config={'apiKey': 'YOUR_KEY', 'secret': 'YOUR_SECRET'}
)

# 添加数据源

data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    use_websocket=True  # 使用 WebSocket 获取实时数据

)

cerebro.adddata(data)
cerebro.setbroker(store.getbroker())

```

#### CTP (期货)

```python
from backtrader.stores import CTPStore
from backtrader.feeds import CTPData

# 创建存储

store = CTPStore(
    userid='YOUR_ID',
    password='YOUR_PASSWORD',
    brokerid='9999',  # SimNow
    appid='simnow_client',
    authcode='0000000000000000'
)

# 添加数据源

data = CTPData(
    store=store,
    dataname='au2506',  # 合约
    timeframe=bt.TimeFrame.Minutes
)

cerebro.adddata(data)
cerebro.setbroker(store.getbroker())

```

## 多数据源

```python
cerebro = bt.Cerebro()

# 添加多个数据源

data1 = bt.feeds.YahooFinanceData(dataname='AAPL', ...)
data2 = bt.feeds.YahooFinanceData(dataname='MSFT', ...)
data3 = bt.feeds.YahooFinanceData(dataname='GOOGL', ...)

cerebro.adddata(data1, name='AAPL')
cerebro.adddata(data2, name='MSFT')
cerebro.adddata(data3, name='GOOGL')

# 在策略中访问

class MyStrategy(bt.Strategy):
    def next(self):
        aapl_price = self.datas[0].close[0]
        msft_price = self.datas[1].close[0]  # 或 self.msft.close[0]
        googl_price = self.datas[2].close[0]  # 或 self.googl.close[0]

```

## 数据重采样

将数据转换为不同的时间周期。

```python

# 原始数据是分钟级

data = bt.feeds.CSVGeneric(dataname='minute_data.csv', ...)

# 重采样为日线

cerebro = bt.Cerebro()
cerebro.resampledata(data, timeframe=bt.TimeFrame.Days)
cerebro.adddata(data, name='daily')

```

## 数据过滤

### 交易日过滤

```python

# 只在特定日期交易

data = bt.feeds.CSVGeneric(dataname='data.csv', ...)
data.addfilter(bt.filters.CalendarDays())

```

### 交易时段过滤

```python

# 只在正常交易时段交易

data = bt.feeds.CSVGeneric(dataname='data.csv', ...)
data.addfilter(bt.filters.SessionFilter(
    starttime=datetime.time(9, 30),
    endtime=datetime.time(16, 0)
))

```

## 数据要求

### 最小数据格式

每个数据源至少需要：

| 字段 | 必需 | 描述 |

|------|------|------|

| datetime | 是 | K 线时间戳 |

| open | 是 | 开盘价 |

| high | 是 | 最高价 |

| low | 是 | 最低价 |

| close | 是 | 收盘价 |

| volume | 否 | 成交量 |

| openinterest | 否 | 持仓量 (期货) |

### CSV 格式示例

```text
datetime,open,high,low,close,volume
2023-01-01,100.0,102.5,99.5,101.0,1000000
2023-01-02,101.0,103.0,100.5,102.5,1200000
2023-01-03,102.5,104.0,102.0,103.0,900000

```

## 下一步学习

- [指标](indicators.md) - 在数据上使用指标
- [策略](strategies.md) - 构建交易策略
- [实盘交易](../CCXT_LIVE_TRADING_GUIDE.md) - 实时交易
