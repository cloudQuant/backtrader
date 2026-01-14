# 数据源使用指南

本指南详细介绍 Backtrader 支持的各种数据源及其使用方法。

## 数据源类型

Backtrader 支持多种数据源：

1. **文件数据源**
   - CSV 文件
   - Pandas DataFrame
   - HDF5 文件

2. **在线数据源**
   - Yahoo Finance
   - Interactive Brokers
   - MT4/MT5

3. **实时数据源**
   - WebSocket
   - REST API
   - 自定义数据源

## CSV 数据源

### 基本用法

```python
import backtrader as bt

data = bt.feeds.GenericCSVData(
    dataname='data.csv',
    datetime=0,      # 日期时间列
    open=1,          # 开盘价列
    high=2,          # 最高价列
    low=3,           # 最低价列
    close=4,         # 收盘价列
    volume=5,        # 成交量列
    openinterest=-1  # 未平仓量列（-1表示不使用）
)
```

### 自定义 CSV 格式

```python
class MyCSVData(bt.feeds.GenericCSVData):
    params = (
        ('datetime', 0),
        ('open', 1),
        ('high', 2),
        ('low', 3),
        ('close', 4),
        ('volume', 5),
        ('openinterest', -1),
        
        ('dtformat', '%Y-%m-%d'),     # 日期格式
        ('tmformat', '%H:%M:%S'),     # 时间格式
        
        ('delimiter', ','),           # 分隔符
        ('headerlines', 1),          # 标题行数
    )
```

## Pandas 数据源

### 基本用法

```python
import pandas as pd
import backtrader as bt

# 读取数据
df = pd.read_csv('data.csv')

# 创建数据源
data = bt.feeds.PandasData(
    dataname=df,
    datetime='date',    # 日期列名
    open='open',        # 开盘价列名
    high='high',        # 最高价列名
    low='low',          # 最低价列名
    close='close',      # 收盘价列名
    volume='volume',    # 成交量列名
    openinterest=None   # 不使用未平仓量
)
```

### 自定义 Pandas 数据源

```python
class MyPandasData(bt.feeds.PandasData):
    params = (
        ('datetime', 'date'),
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', None),
    )
    
    def __init__(self):
        super(MyPandasData, self).__init__()
```

## 在线数据源

### Yahoo Finance

```python
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',  # 股票代码
    fromdate=datetime.datetime(2020, 1, 1),
    todate=datetime.datetime(2023, 12, 31),
    reverse=False
)
```

### Interactive Brokers

```python
from backtrader.feeds import IBData

data = IBData(
    dataname='AAPL',  # 股票代码
    sectype='STK',    # 证券类型
    exchange='SMART', # 交易所
    currency='USD'    # 货币
)
```

## 实时数据源

### WebSocket 数据源

```python
class WebSocketData(bt.feeds.DataBase):
    def __init__(self):
        super(WebSocketData, self).__init__()
        self.ws = None
        
    def start(self):
        super(WebSocketData, self).start()
        self.ws = websocket.WebSocketApp(
            "wss://example.com/ws",
            on_message=self._on_message
        )
        
    def _on_message(self, ws, message):
        # 处理接收到的数据
        pass
```

### REST API 数据源

```python
class RestApiData(bt.feeds.DataBase):
    params = (
        ('url', ''),
        ('apikey', ''),
    )
    
    def __init__(self):
        super(RestApiData, self).__init__()
        
    def start(self):
        super(RestApiData, self).start()
        self._get_data()
        
    def _get_data(self):
        response = requests.get(
            self.p.url,
            headers={'apikey': self.p.apikey}
        )
        # 处理响应数据
```

## 数据预处理

### 重采样

```python
# 将分钟数据重采样为日线数据
cerebro.resampledata(
    data,
    timeframe=bt.TimeFrame.Days,
    compression=1
)
```

### 数据过滤

```python
# 过滤掉成交量为0的数据
class VolumeFilter(bt.filters.DataFilter):
    def __init__(self):
        super(VolumeFilter, self).__init__()
        
    def next(self):
        if self.data.volume[0] > 0:
            return True
        return False
```

## 多数据源

### 同时使用多个数据源

```python
# 添加股票数据
cerebro.adddata(stock_data)
# 添加指数数据
cerebro.adddata(index_data)
# 添加期货数据
cerebro.adddata(futures_data)
```

### 数据源同步

```python
# 确保所有数据源在同一时间范围内
cerebro.adddata(data1, name='AAPL')
cerebro.adddata(data2, name='GOOGL')
cerebro.synchronize()
```

## 最佳实践

### 1. 数据验证

```python
def validate_data(data):
    # 检查是否有缺失值
    if data.isnull().any().any():
        print("警告：数据中存在缺失值")
    
    # 检查时间序列是否连续
    dates = data.index
    if not dates.is_monotonic_increasing:
        print("警告：时间序列不连续")
```

### 2. 数据缓存

```python
class CachedData(bt.feeds.GenericCSVData):
    def __init__(self):
        super(CachedData, self).__init__()
        self._cache = {}
        
    def _load(self):
        if self._filename in self._cache:
            return self._cache[self._filename]
        data = super(CachedData, self)._load()
        self._cache[self._filename] = data
        return data
```

### 3. 错误处理

```python
def safe_data_load(filename):
    try:
        data = bt.feeds.GenericCSVData(dataname=filename)
        return data
    except Exception as e:
        print(f"加载数据失败: {e}")
        return None
```

## 常见问题

1. **数据加载失败**
   - 检查文件格式
   - 验证数据完整性
   - 确认文件权限

2. **数据不同步**
   - 检查时间戳格式
   - 确保时区一致
   - 验证数据频率

3. **内存使用过高**
   - 使用数据过滤
   - 实现数据分块
   - 优化数据结构

## 下一步

- 学习[策略开发](./strategies.md)
- 了解[指标系统](./indicators.md)
- 探索[参数优化](./optimization.md)
- 研究[实盘交易](../advanced/live_trading.md)
