---
title: 数据源 API
description: Backtrader 完整数据源 API 参考
---

# 数据源 API

数据源是 Backtrader 中回测和实盘交易的行情数据来源。它们提供带有时间索引的 OHLCV（开盘、最高、最低、收盘、成交量、持仓量）数据。

## 类层次结构

```
AbstractDataBase (所有数据源的基类)
    DataBase (功能完整的数据源)
        CSVDataBase (CSV 文件解析)
            GenericCSVData
            YahooFinanceCSVData
            BacktraderCSVData
        PandasData (DataFrame 集成)
        CCXTFeed (加密货币交易所)
        ... 以及更多
```

## 核心类

### `backtrader.AbstractDataBase`

所有数据源实现的基础类。

```python
class backtrader.AbstractDataBase:
    """所有数据源实现的基础类。"""
```

#### 参数

| 参数 | 类型 | 默认值 | 描述 |
|-----|------|--------|------|
| `dataname` | Any | None | 数据源标识符（文件名、URL、DataFrame 等） |
| `name` | str | "" | 数据源的显示名称 |
| `compression` | int | 1 | 时间周期压缩因子 |
| `timeframe` | TimeFrame | TimeFrame.Days | 时间周期类型 |
| `fromdate` | datetime | None | 数据过滤的起始日期 |
| `todate` | datetime | None | 数据过滤的结束日期 |
| `sessionstart` | time | time.min | 交易时段开始时间 |
| `sessionend` | time | time(23, 59, 59, 999990) | 交易时段结束时间 |
| `tz` | str | None | 输出时区 |
| `tzinput` | str | None | 输入时区 |
| `calendar` | str/Calendar | None | 使用的交易日历 |

#### 数据状态

| 状态 | 描述 |
|-----|------|
| `CONNECTED` | 数据源已连接 |
| `DISCONNECTED` | 数据源已断开 |
| `CONNBROKEN` | 连接中断 |
| `DELAYED` | 数据延迟 |
| `LIVE` | 实时数据流 |
| `NOTSUBSCRIBED` | 未订阅数据 |
| `NOTSUPPORTED_TF` | 不支持的时间周期 |
| `UNKNOWN` | 未知状态 |

### `backtrader.DataBase`

功能完整的数据源类。继承 `AbstractDataBase` 的所有功能。

```python
class backtrader.DataBase(backtrader.AbstractDataBase):
    """功能完整的数据源类。"""
```

## Line 系统

数据源使用 "Line" 系统进行时间序列数据访问。每个数据源提供以下 line：

### 标准 Line

| Line | 描述 |
|------|------|
| `datetime` | K线时间戳 |
| `open` | 开盘价 |
| `high` | 最高价 |
| `low` | 最低价 |
| `close` | 收盘价 |
| `volume` | 成交量 |
| `openinterest` | 持仓量（用于衍生品） |

### 访问 Line 数据

```python
class MyStrategy(bt.Strategy):
    def next(self):
        # 当前K线值（索引 0）
        current_close = self.data.close[0]
        current_datetime = self.data.datetime.datetime(0)

        # 前一根K线值（负索引）
        prev_close = self.data.close[-1]
        prev_high = self.data.high[-2]

        # 数据长度
        current_len = len(self.data)
```

### 数据索引

| 索引 | 含义 |
|-----|------|
| `0` | 当前K线（最新） |
| `-1` | 前一根K线 |
| `-2`, `-3`, ... | 历史K线 |
| `1` | 下一根K线（仅在重放/实盘场景中） |

## TimeFrame（时间周期）

`TimeFrame` 类定义了金融数据的时间周期。

### TimeFrame 常量

| 常量 | 值 | 描述 |
|-----|-----|------|
| `TimeFrame.Ticks` | 1 | Tick 级别数据 |
| `TimeFrame.MicroSeconds` | 2 | 微秒 |
| `TimeFrame.Seconds` | 3 | 秒 |
| `TimeFrame.Minutes` | 4 | 分钟 |
| `TimeFrame.Days` | 5 | 天 |
| `TimeFrame.Weeks` | 6 | 周 |
| `TimeFrame.Months` | 7 | 月 |
| `TimeFrame.Years` | 8 | 年 |
| `TimeFrame.NoTimeFrame` | 9 | 无时间周期 |

### TimeFrame 方法

```python
# 获取时间周期名称
name = bt.TimeFrame.getname(bt.TimeFrame.Days)  # 返回 'Day'
name = bt.TimeFrame.getname(bt.TimeFrame.Minutes, 5)  # 返回 'Minutes'

# 从名称获取常量
tf = bt.TimeFrame.TFrame('Days')  # 返回 TimeFrame.Days

# 从常量获取名称
name = bt.TimeFrame.TName(bt.TimeFrame.Days)  # 返回 'Days'
```

## 内置数据源

### CSV 数据源

#### GenericCSVData

解析可配置列映射的 CSV 文件。

```python
data = bt.feeds.GenericCSVData(
    dataname='data.csv',
    datetime=0,      # 时间戳列索引
    time=-1,         # 时间列索引（无则为-1）
    open=1,          # 开盘价列索引
    high=2,          # 最高价列索引
    low=3,           # 最低价列索引
    close=4,         # 收盘价列索引
    volume=5,        # 成交量列索引
    openinterest=6,  # 持仓量列索引
    dtformat='%Y-%m-%d %H:%M:%S',  # 时间格式
    tmformat='%H:%M:%S',  # 时间格式
    nullvalue=float('NaN'),  # 缺失字段值
    separator=',',    # CSV 分隔符
    headers=True,     # 如果为 True 则跳过首行
)
```

**CSV 参数：**

| 参数 | 类型 | 默认值 | 描述 |
|-----|------|--------|------|
| `dataname` | str/file | 必填 | CSV 文件名或类文件对象 |
| `datetime` | int | 0 | 时间戳列索引 |
| `time` | int | -1 | 时间列索引（无则为-1） |
| `open` | int | 1 | 开盘价列索引 |
| `high` | int | 2 | 最高价列索引 |
| `low` | int | 3 | 最低价列索引 |
| `close` | int | 4 | 收盘价列索引 |
| `volume` | int | 5 | 成交量列索引 |
| `openinterest` | int | 6 | 持仓量列索引 |
| `dtformat` | str/int/callable | "%Y-%m-%d %H:%M:%S" | 时间格式或 1/2 表示 Unix 时间戳 |
| `tmformat` | str | "%H:%M:%S" | 时间格式 |
| `nullvalue` | float | NaN | 缺失字段的填充值 |
| `separator` | str | "," | CSV 分隔符 |
| `headers` | bool | True | 是否跳过首行 |

**dtformat 值：**

| 值 | 含义 |
|-----|------|
| `"%Y-%m-%d"` | strptime 使用的字符串格式 |
| `1` | Unix 时间戳（int，自纪元以来的秒数） |
| `2` | Unix 时间戳（float，自纪元以来的秒数） |
| `callable` | 将字符串转换为 datetime 的函数 |

#### YahooFinanceCSVData

解析 Yahoo Finance 格式的 CSV 文件。

```python
data = bt.feeds.YahooFinanceCSVData(
    dataname='yahoo.csv',
    reverse=False,     # 数据按时间顺序排列
    adjclose=True,     # 使用复权收盘价
    adjvolume=True,    # 使用复权时调整成交量
    round=True,        # 对价格进行四舍五入
    decimals=2,        # 四舍五入的小数位数
)
```

**Yahoo CSV 参数：**

| 参数 | 类型 | 默认值 | 描述 |
|-----|------|--------|------|
| `reverse` | bool | False | 如果数据按逆时间顺序排列则设为 True |
| `adjclose` | bool | True | 使用分红/拆股调整后的收盘价 |
| `adjvolume` | bool | True | 根据调整因子调整成交量 |
| `round` | bool | True | 将价格四舍五入 |
| `decimals` | int | 2 | 四舍五入的小数位数 |
| `roundvolume` | int/bool | False | 将成交量四舍五入到 N 位小数 |

#### BacktraderCSVData

解析 backtrader 测试 CSV 格式。

```python
data = bt.feeds.BacktraderCSVData(dataname='test.csv')
```

格式：`YYYY-MM-DD [HH:MM:SS] open high low close volume openinterest`

### Pandas 数据源

#### PandasData

使用 pandas DataFrame 作为数据源，通过列名匹配。

```python
import pandas as pd

# 创建标准列名的 DataFrame
df = pd.DataFrame({
    'datetime': pd.date_range('2020-01-01', periods=100),
    'open': np.random.randn(100).cumsum() + 100,
    'high': np.random.randn(100).cumsum() + 102,
    'low': np.random.randn(100).cumsum() + 98,
    'close': np.random.randn(100).cumsum() + 100,
    'volume': np.random.randint(1000, 10000, 100),
})

# 将 DataFrame 作为数据源
data = bt.feeds.PandasData(dataname=df)

# 或使用自定义列名
data = bt.feeds.PandasData(
    dataname=df,
    datetime=None,    # None 表示使用索引
    open='open_price',
    high='high_price',
    low='low_price',
    close='close_price',
    volume='vol',
    openinterest=None,  # None 表示列不存在
    nocase=True,       # 不区分大小写的列匹配
)
```

**PandasData 参数：**

| 参数 | 类型 | 默认值 | 描述 |
|-----|------|--------|------|
| `dataname` | DataFrame | 必填 | Pandas DataFrame |
| `datetime` | None/int/str | None | datetime 列（None = 使用索引） |
| `open` | None/-1/int/str | -1 | 开盘价列（-1 = 自动检测） |
| `high` | None/-1/int/str | -1 | 最高价列 |
| `low` | None/-1/int/str | -1 | 最低价列 |
| `close` | None/-1/int/str | -1 | 收盘价列 |
| `volume` | None/-1/int/str | -1 | 成交量列 |
| `openinterest` | None/-1/int/str | -1 | 持仓量列 |
| `nocase` | bool | True | 不区分大小写的列匹配 |

**列值含义：**

| 值 | 含义 |
|-----|------|
| `None` | DataFrame 中不存在该列 |
| `-1` | 按名称自动检测列 |
| `0, 1, 2...` | 数字列索引 |
| `"column_name"` | 字符串列名 |

#### PandasDirectData

直接使用 DataFrame 元组进行更快迭代。

```python
data = bt.feeds.PandasDirectData(
    dataname=df,  # 带列索引位置的 DataFrame
    datetime=0,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=6,
)
```

### 实时/在线数据源

#### CCXTFeed（加密货币）

通过 CCXT 库连接加密货币交易所。

```python
# REST API 轮询
data = bt.feeds.CCXTFeed(
    exchange='binance',
    symbol='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    historical=False,      # 仅下载历史数据后停止
    backfill_start=True,   # 启动时回填历史数据
    ohlcv_limit=100,       # 每次 REST 请求的K线数
    drop_newest=False,     # 删除最新（可能不完整）的K线
)

# 使用 WebSocket（需要 ccxt.pro）
data = bt.feeds.CCXTFeed(
    exchange='binance',
    symbol='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    use_websocket=True,           # 启用 WebSocket
    ws_reconnect_delay=5.0,        # 重连延迟（秒）
    ws_max_reconnect_delay=60.0,   # 最大重连延迟
)
```

**CCXTFeed 参数：**

| 参数 | 类型 | 默认值 | 描述 |
|-----|------|--------|------|
| `exchange` | str | 必填 | 交易所名称（binance、kraken 等） |
| `symbol` | str | 必填 | 交易对（BTC/USDT、ETH/USD 等） |
| `historical` | bool | False | 下载历史数据后停止 |
| `backfill_start` | bool | True | 启动时回填历史数据 |
| `ohlcv_limit` | int | 100 | 每次 REST 请求的最大K线数 |
| `drop_newest` | bool | False | 删除最新（可能不完整）的K线 |
| `use_websocket` | bool | False | 使用 WebSocket 获取实时数据 |
| `ws_reconnect_delay` | float | 5.0 | WebSocket 重连延迟 |
| `ws_max_reconnect_delay` | float | 60.0 | 最大重连延迟 |

#### YahooFinanceData

直接从 Yahoo Finance 下载数据（需要 `requests` 库）。

```python
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',        # 股票代码
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31),
    timeframe=bt.TimeFrame.Days,
    period='d',             # 'd'=日, 'w'=周, 'm'=月
    adjclose=True,          # 使用复权价格
    proxies={},             # 代理配置
    retries=3,              # 下载重试次数
)
```

### 其他数据源

#### Quandl

```python
data = bt.feeds.Quandl(
    dataname='WIKI/AAPL',
    apikey='YOUR_API_KEY',
    fromdate=datetime(2020, 1, 1),
)
```

#### Interactive Brokers

```python
data = bt.feeds.IBData(
    dataname='AAPL',
    host='127.0.0.1',
    port=7496,
    clientId=1,
)
```

#### OANDA

```python
data = bt.feeds.OandaData(
    dataname='EUR_USD',
    account='YOUR_ACCOUNT',
    access_token='YOUR_TOKEN',
)
```

## 数据源方法

### 生命周期方法

#### `start(self)`

回测开始时调用。打开文件、连接数据源。

```python
# 在自定义数据源中重写
class MyFeed(bt.CSVDataBase):
    def start(self):
        super().start()
        # 自定义初始化
```

#### `stop(self)`

回测结束时调用。关闭文件、断开连接。

```python
def stop(self):
    # 自定义清理
    super().stop()
```

#### `preload(self)`

在回测前将所有数据加载到内存。

```python
# 使用 cerebro.run(preload=True) 自动预加载
data = bt.feeds.PandasData(dataname=df)
data.preload()  # 手动预加载
```

### 数据访问方法

#### `date2num(self, dt)`

将 datetime 转换为内部数字格式。

```python
dt_num = data.date2num(datetime(2023, 1, 1))
```

#### `num2date(self, dt=None, tz=None, naive=True)`

将内部数字格式转换为 datetime。

```python
dt = data.num2date()  # 当前K线的 datetime
dt = data.num2date(data.lines.datetime[-1])  # 前一根K线
```

### 克隆方法

#### `clone(self, **kwargs)`

创建此数据源的克隆。

```python
data_clone = data.clone()  # 完全复制
data_clone = data.clone(timeframe=bt.TimeFrame.Weeks)  # 不同时间周期
```

#### `copyas(self, _dataname, **kwargs)`

以不同名称复制。

```python
data_copy = data.copyas('AAPL_Copy')
```

### 状态方法

#### `islive(self)`

如果这是实时数据源则返回 True。

```python
if data.islive():
    print("这是实时数据源")
```

#### `haslivedata(self)`

如果实时数据可用则返回 True。

#### `get_notifications(self)`

获取待处理的状态通知。

```python
notifs = data.get_notifications()
for status, args, kwargs in notifs:
    print(f"状态: {status}")
```

## 数据过滤器

### 添加过滤器

过滤器在数据加载时修改或删除K线。

```python
# 添加简单过滤器
data.addfilter(lambda x: x.close[0] > x.open[0])  # 仅保留阳线

# 添加过滤器类
data.addfilter(bt.filters.SessionData, session_end=time(15, 0))
```

### 内置过滤器

#### SessionFilter

按特定交易时段过滤K线。

```python
data.addfilter(bt.filters.SessionFilter)
```

#### SessionData

填充缺失的时段数据。

```python
data.addfilter(bt.filters.SessionData)
```

#### CalendarFilter

基于交易日历过滤。

```python
data.addfilter(bt.filters.CalendarFilter)
```

## 重采样和回放

### 重采样

将数据转换为不同时间周期。

```python
# 将分钟数据重采样为小时数据
data = bt.feeds.GenericCSVData(dataname='minute_data.csv')
data.resample(
    timeframe=bt.TimeFrame.Minutes,
    compression=60,  # 60 分钟 = 1 小时
)

# 在 Cerebro 中
cerebro.resampledata(data, timeframe=bt.TimeFrame.Weeks, compression=1)
```

### 回放

精确控制地将 tick 数据处理为K线。

```python
data.replay(
    timeframe=bt.TimeFrame.Minutes,
    compression=5,
    bar2edge=True,       # 将K线对齐到时间周期边界
    rightedge=True,      # 使用右边缘作为时间戳
    boundoff=0,          # 边界偏移量
)

# 在 Cerebro 中
cerebro.replaydata(data, timeframe=bt.TimeFrame.Days)
```

## 自定义数据源

### 创建自定义 CSV 数据源

```python
import backtrader as bt
from datetime import datetime

class MyCSVData(bt.CSVDataBase):
    """自定义 CSV 解析器，用于我的数据格式。"""

    params = (
        ('dtformat', '%d/%m/%Y'),
        ('separator', ';'),
    )

    def _loadline(self, linetokens):
        # 解析 datetime
        dt_str = linetokens[0]
        dt = datetime.strptime(dt_str, self.p.dtformat)

        # 转换为内部格式
        self.lines.datetime[0] = self.date2num(dt)

        # 解析 OHLCV
        self.lines.open[0] = float(linetokens[1])
        self.lines.high[0] = float(linetokens[2])
        self.lines.low[0] = float(linetokens[3])
        self.lines.close[0] = float(linetokens[4])
        self.lines.volume[0] = float(linetokens[5])
        self.lines.openinterest[0] = 0.0

        return True
```

### 创建自定义实时数据源

```python
class MyLiveData(bt.DataBase):
    """自定义实时数据源。"""

    params = (('api_url', 'https://api.example.com'),)

    def __init__(self):
        super().__init__()
        self.api_url = self.p.api_url

    def start(self):
        super().start()
        # 连接到数据源
        self.connected = True
        self.put_notification(self.CONNECTED)

    def stop(self):
        # 断开连接
        self.connected = False
        super().stop()

    def _load(self):
        # 从 API 获取下一根K线
        try:
            import requests
            response = requests.get(self.api_url)
            bar_data = response.json()

            # 解析并设置数据
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
```

### 创建带自定义 Line 的数据源

```python
class ExtendedData(bt.feeds.PandasData):
    """带有额外 line 的数据源。"""

    # 添加自定义 lines
    lines = ('adj_close', 'dividend',)

    # 映射到 DataFrame 列
    params = (
        ('adj_close', -1),
        ('dividend', -1),
    )
```

## 使用多个数据源

### 添加多个数据源

```python
# 添加多个数据源
cerebro.adddata(bt.feeds.PandasData(dataname=df_aapl), name='AAPL')
cerebro.adddata(bt.feeds.PandasData(dataname=df_msft), name='MSFT')
cerebro.adddata(bt.feeds.PandasData(dataname=df_goog), name='GOOGL')

class MyStrategy(bt.Strategy):
    def __init__(self):
        self.aapl = self.getdatabyname('AAPL')
        self.msft = self.getdatabyname('MSFT')
        self.goog = self.getdatabyname('GOOGL')

    def next(self):
        # 访问不同的数据源
        if self.aapl.close[0] > self.msft.close[0]:
            self.buy(data=self.aapl)
```

### 数据源同步

```python
# 主从关系
data_daily = bt.feeds.PandasData(dataname=daily_df, name='daily')
data_hourly = bt.feeds.PandasData(dataname=hourly_df, name='hourly')

# 小时数据将同步到日边界
cerebro.adddata(data_daily)
cerebro.adddata(data_hourly)
```

## 性能优化

### 预加载

```python
# 对于使用历史数据的快速回测
cerebro.run(preload=True)
```

### 内存管理

```python
# 限制大数据集的内存使用
data = bt.feeds.PandasData(dataname=large_df)
cerebro.adddata(data)
data.qbuffer(savemem=1000)  # 仅在内存中保留 1000 根K线
```

### 禁用缓存

```python
# 对小数据集禁用优化
cerebro.run preload=True, runonce=True, exactbars=False
```

## 完整示例

### 示例 1：CSV 回测

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

# 创建 cerebro
cerebro = bt.Cerebro()

# 添加 CSV 数据
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

# 添加策略
cerebro.addstrategy(SmaCross)

# 运行
results = cerebro.run()
```

### 示例 2：Pandas DataFrame

```python
import backtrader as bt
import pandas as pd

# 加载数据
df = pd.read_csv('data.csv', parse_dates=['date'], index_col='date')

# 创建数据源
data = bt.feeds.PandasData(
    dataname=df,
    datetime=None,  # 使用索引
    open='open',
    high='high',
    low='low',
    close='close',
    volume='volume',
)

# 创建 cerebro 并添加数据
cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.run()
```

### 示例 3：重采样

```python
import backtrader as bt

# 加载分钟数据
data = bt.feeds.GenericCSVData(dataname='minute_data.csv')

# 创建 cerebro
cerebro = bt.Cerebro()

# 添加重采样数据（小时）
cerebro.resampledata(
    data,
    timeframe=bt.TimeFrame.Minutes,
    compression=60,
    bar2edge=True,
    rightedge=True,
)

# 添加原始数据以供比较
cerebro.adddata(data, name='minutes')

# 运行
cerebro.run()
```

### 示例 4：多数据源

```python
import backtrader as bt

class MultiAssetStrategy(bt.Strategy):
    def __init__(self):
        # 存储数据源
        self.data1 = self.datas[0]
        self.data2 = self.datas[1]

        # 为每个数据源创建指标
        self.sma1 = bt.indicators.SMA(self.data1.close, period=20)
        self.sma2 = bt.indicators.SMA(self.data2.close, period=20)

    def next(self):
        # 基于两个数据源进行交易
        if self.sma1[0] > self.sma2[0]:
            if not self.getposition(self.data1):
                self.buy(data=self.data1)

cerebro = bt.Cerebro()

# 添加多个数据源
cerebro.adddata(bt.feeds.PandasData(dataname=df1), name='Asset1')
cerebro.adddata(bt.feeds.PandasData(dataname=df2), name='Asset2')

cerebro.addstrategy(MultiAssetStrategy)
cerebro.run()
```

## 相关文档

- [策略 API](strategy_zh.md) - 策略开发
- [指标 API](indicator_zh.md) - 技术指标
- [Cerebro API](cerebro_zh.md) - 回测引擎
