# Signal、Timer 和 Store API 参考文档

本文档提供了 Backtrader 三个重要 API 的综合参考：

1. **Signal API**- 基于信号指标的声明式交易

2.**Timer API**- 回测期间基于时间的事件调度
3.**Store API** - 外部数据源和经纪商连接管理

---
## Signal API

Signal API 提供了一种声明式的交易方法，交易决策由信号指标驱动，而非显式的下单逻辑。信号是用于指示何时入场或退场的数值。

### 信号类型

以下信号类型常量定义在 `backtrader.signal` 模块中：

| 常量 | 值 | 描述 |

|------|-----|------|

| `SIGNAL_NONE` | 0 | 无信号 |

| `SIGNAL_LONGSHORT` | 1 | 此指标同时提供多头和空头信号 |

| `SIGNAL_LONG` | 2 | 多头入场信号（正值=多头，负值=退出多头） |

| `SIGNAL_LONG_INV` | 3 | 反向多头信号 |

| `SIGNAL_LONG_ANY` | 4 | 任何非零值都是多头信号 |

| `SIGNAL_SHORT` | 5 | 空头入场信号（负值=空头，正值=退出空头） |

| `SIGNAL_SHORT_INV` | 6 | 反向空头信号 |

| `SIGNAL_SHORT_ANY` | 7 | 任何非零值都是空头信号 |

| `SIGNAL_LONGEXIT` | 8 | 多头退出信号（负值=退出多头） |

| `SIGNAL_LONGEXIT_INV` | 9 | 反向多头退出信号 |

| `SIGNAL_LONGEXIT_ANY` | 10 | 任何非零值都退出多头 |

| `SIGNAL_SHORTEXIT` | 11 | 空头退出信号（正值=退出空头） |

| `SIGNAL_SHORTEXIT_INV` | 12 | 反向空头退出信号 |

| `SIGNAL_SHORTEXIT_ANY` | 13 | 任何非零值都退出空头 |

### Signal 类

```python
class backtrader.Signal(data)

```
`Signal` 类包装一条数据线以提供交易信号值。它继承自 `Indicator` 并公开一条信号线。

- *示例：从指标创建信号**

```python
import backtrader as bt

class MyStrategy(bt.SignalStrategy):
    def __init__(self):

# 从指标交叉创建信号
        sma_fast = bt.indicators.SMA(period=10)
        sma_slow = bt.indicators.SMA(period=30)

# 当快速 SMA 上穿慢速 SMA 时添加多头信号
        self.signal_add(bt.SIGNAL_LONG, bt.ind.CrossOver(sma_fast, sma_slow))

```

### SignalStrategy 类

```python
class backtrader.SignalStrategy

```
`SignalStrategy` 是一个专门的 `Strategy` 子类，它会根据信号指标自动执行交易。

#### 参数

| 参数 | 默认值 | 描述 |

|------|--------|------|

| `signals` | `[]` | 信号定义列表（通常通过 `cerebro.add_signal()` 设置） |

| `_accumulate` | `False` | 允许在已有持仓的情况下继续入市（加仓） |

| `_concurrent` | `False` | 允许多个订单同时存在 |

#### 方法

##### signal_add()

```python
def signal_add(self, sigtype, signal)

```
向策略添加一个信号指标。

- *参数：**
- `sigtype`：信号类型常量（如 `SIGNAL_LONG`、`SIGNAL_SHORT`）
- `signal`：信号指标实例

- *示例：**

```python
class MySignalStrategy(bt.SignalStrategy):
    def __init__(self):
        super().__init__()

# 创建自定义信号
        rsi = bt.indicators.RSI(period=14)

# 创建信号条件：RSI < 30 = 多头信号
        rsi_signal = (30 - rsi)  # RSI < 30 时为正

        self.signal_add(bt.SIGNAL_LONG, rsi_signal)

```

#### 信号处理逻辑

`SignalStrategy` 按以下顺序评估信号：

1. **首先检查退出信号**
   - `LONGEXIT`：负值触发多头平仓
   - `SHORTEXIT`：正值触发空头平仓

1. **入场信号在退出之后检查**
   - `LONGSHORT`：根据符号同时支持多头和空头
   - `LONG`：正值=多头，负值=平多头
   - `SHORT`：负值=空头，正值=平空头

1. **订单执行**
   - 订单以市价单方式下单
   - 有效期为"撤销前有效"（Good-Until-Canceled）

#### 完整的信号策略示例

```python
import backtrader as bt

class MultiSignalStrategy(bt.SignalStrategy):
    """使用多种信号类型的策略。"""

    def __init__(self):
        super().__init__()

# 指标
        sma_fast = bt.indicators.SMA(period=10)
        sma_slow = bt.indicators.SMA(period=30)
        rsi = bt.indicators.RSI(period=14)

# 多头入场：快速 SMA 上穿慢速 SMA
        long_signal = bt.ind.CrossOver(sma_fast, sma_slow)
        self.signal_add(bt.SIGNAL_LONG, long_signal)

# 空头入场：快速 SMA 下穿慢速 SMA
        short_signal = bt.ind.CrossOver(sma_slow, sma_fast)
        self.signal_add(bt.SIGNAL_SHORT, short_signal)

# 多头退出：RSI 超过 70
        long_exit = (rsi - 70)  # RSI > 70 时为正
        self.signal_add(bt.SIGNAL_LONGEXIT, long_exit)

# 空头退出：RSI 低于 30
        short_exit = (30 - rsi)  # RSI < 30 时为正
        self.signal_add(bt.SIGNAL_SHORTEXIT, short_exit)

# 使用

cerebro = bt.Cerebro()
data = bt.feeds.YahooFinanceData(dataname='AAPL', fromdate=datetime(2020, 1, 1))
cerebro.adddata(data)
cerebro.addstrategy(MultiSignalStrategy)
results = cerebro.run()

```

### 使用 cerebro.add_signal()

```python
cerebro.add_signal(sigtype, sigcls, *sigargs, **sigkwargs)

```
通过 cerebro 向策略添加信号。

- *参数：**
- `sigtype`：信号类型常量
- `sigcls`：信号类（通常是 `bt.Signal` 或其子类）
- `*sigargs`：传递给信号类的位置参数
- `**sigkwargs`：传递给信号类的关键字参数

- *示例：**

```python

# 添加一个简单的基于价格的信号

cerebro.add_signal(
    bt.SIGNAL_LONGSHORT,
    bt.Signal,
    data  # 使用数据的收盘价作为信号

)

# 使用自定义信号指标

cerebro.add_signal(
    bt.SIGNAL_LONG,
    bt.ind.CrossOver,
    bt.indicators.SMA(period=10),
    bt.indicators.SMA(period=30)
)

```

### 信号策略的常见模式

#### 模式 1：简单的交叉信号

```python
class CrossSignalStrategy(bt.SignalStrategy):
    """基于均线交叉的简单信号策略。"""

    def __init__(self):
        super().__init__()

# 快速和慢速均线
        fast_sma = bt.indicators.SMA(period=10)
        slow_sma = bt.indicators.SMA(period=30)

# 交叉信号
        crossover = bt.ind.CrossOver(fast_sma, slow_sma)

# 使用 LONGSHORT 让交叉信号同时处理多空
        self.signal_add(bt.SIGNAL_LONGSHORT, crossover)

```

#### 模式 2：分离的入出场信号

```python
class SeparatedSignalStrategy(bt.SignalStrategy):
    """使用独立入场和退出信号的策略。"""

    def __init__(self):
        super().__init__()

# 趋势指标用于入场
        macd = bt.indicators.MACD()
        macd_cross = bt.ind.CrossOver(macd.macd, macd.signal)

# 震荡指标用于出场
        rsi = bt.indicators.RSI(period=14)

# 多头：MACD 金叉
        self.signal_add(bt.SIGNAL_LONG, macd_cross)

# 多头退出：RSI 超买
        long_exit = (rsi - 70)
        self.signal_add(bt.SIGNAL_LONGEXIT, long_exit)

```

#### 模式 3：累积模式

```python
class AccumulatingSignalStrategy(bt.SignalStrategy):
    """允许加仓的信号策略。"""

    params = (
        ('_accumulate', True),  # 允许累积仓位
    )

    def __init__(self):
        super().__init__()

# 每次信号出现都加仓
        rsi = bt.indicators.RSI(period=14)
        rsi_long = (30 - rsi)  # RSI 超卖时为正
        self.signal_add(bt.SIGNAL_LONG, rsi_long)

```

---
## Timer API

Timer API 允许在回测期间调度基于时间的通知。定时器可以在特定时间、会话边界或重复间隔触发。

### Timer 常量

| 常量 | 值 | 描述 |

|------|-----|------|

| `Timer.SESSION_TIME` | 0 | 定时器在特定时间触发 |

| `Timer.SESSION_START` | 1 | 定时器在会话开始时触发 |

| `Timer.SESSION_END` | 2 | 定时器在会话结束时触发 |

### Timer 类

```python
class backtrader.Timer(**kwargs)

```

- *参数：**

| 参数 | 默认值 | 描述 |

|------|--------|------|

| `tid` | `None` | 定时器 ID，用于标识 |

| `owner` | `None` | 定时器的拥有者对象 |

| `strats` | `False` | 是否通知策略 |

| `when` | `None` | 触发时间（time、SESSION_START 或 SESSION_END） |

| `offset` | `timedelta()` | 触发时间偏移 |

| `repeat` | `timedelta()` | 重复定时器的重复间隔 |

| `weekdays` | `[]` | 激活定时器的星期列表（0=星期一，6=星期日） |

| `weekcarry` | `False` | 如果错过是否延至下一工作日 |

| `monthdays` | `[]` | 激活定时器的月份日期列表 |

| `monthcarry` | `True` | 如果错过是否延至下一月日 |

| `allow` | `None` | 回调函数，用于允许/拒绝特定日期的触发 |

| `tzdata` | `None` | 定时器的时区数据 |

| `cheat` | `False` | 定时器是否可以在经纪商之前执行 |

### 策略定时器方法

#### add_timer()

```python
def add_timer(self, when, offset=timedelta(), repeat=timedelta(),
              weekdays=[], weekcarry=False, monthdays=[], monthcarry=True,
              allow=None, tzdata=None, cheat=False, *args, **kwargs)

```
向策略添加一个定时器。

- *参数：**
- `when`：触发时间（`datetime.time`、`SESSION_START` 或 `SESSION_END`）
- `offset`：触发时间的偏移量
- `repeat`：重复间隔（如 `timedelta(minutes=5)`）
- `weekdays`：定时器激活的星期列表
- `weekcarry`：如果错过工作日是否延后
- `monthdays`：定时器激活的月份日期列表
- `monthcarry`：如果错过月日是否延后
- `allow`：回调函数 `allow(date) -> bool` 用于自定义过滤
- `tzdata`：定时器的时区
- `cheat`：为 True 时，定时器可以在经纪商之前执行
- `*args`、`**kwargs`：传递给 `notify_timer` 的额外参数

- *返回值：** 创建的定时器实例

#### notify_timer()

```python
def notify_timer(self, timer, when, *args, **kwargs)

```
重写此方法以接收定时器通知。

- *参数：**
- `timer`：触发的定时器实例
- `when`：定时器被触发的计划时间
- `*args`、`**kwargs`：来自 `add_timer` 的额外参数

### Timer 示例

#### 示例 1：会话开始定时器

```python
import backtrader as bt
from datetime import time

class SessionStartStrategy(bt.Strategy):
    """在市场开盘时执行操作。"""

    def __init__(self):
        self.order_count = 0

# 在会话开始时触发的定时器
        self.add_timer(
            when=bt.Timer.SESSION_START,
            weekdays=[0, 1, 2, 3, 4],  # 星期一到星期五
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        """在会话开始时调用。"""
        self.order_count += 1

# 可以在这里下单、更新指标等
        print(f'会话开始于 {when}')

    def next(self):

# 常规策略逻辑
        pass

```

#### 示例 2：特定时间定时器

```python
class TimeBasedStrategy(bt.Strategy):
    """每天在特定时间执行。"""

    def __init__(self):

# 每个交易日 9:45 AM 触发的定时器
        self.add_timer(
            when=time(9, 45),
            weekdays=[0, 1, 2, 3, 4],
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        print(f'定时器在 {when} 触发')

# 示例：在收盘时取消所有挂单
        for order in self.broker.orders:
            if order.status == order.Submitted:
                self.cancel(order)

```

#### 示例 3：重复定时器

```python
from datetime import timedelta

class RepeatingTimerStrategy(bt.Strategy):
    """每 N 分钟执行一次。"""

    def __init__(self):
        self.execution_count = 0

# 每 30 分钟重复一次的定时器
        self.add_timer(
            when=bt.Timer.SESSION_START,
            repeat=timedelta(minutes=30),
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        self.execution_count += 1
        print(f'重复定时器 #{self.execution_count} 在 {when}')

```

#### 示例 4：月日定时器

```python
class MonthlyRebalanceStrategy(bt.Strategy):
    """在特定日期重新平衡投资组合。"""

    def __init__(self):

# 每月 1 日和 15 日重新平衡
        self.add_timer(
            when=bt.Timer.SESSION_START,
            monthdays=[1, 15],
            monthcarry=True,  # 如果 1 日是周末，使用下一个交易日
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        print(f'月度重新平衡于 {when}')

# 重新平衡逻辑

```

#### 示例 5：自定义允许函数

```python
from datetime import timedelta

class ConditionalTimerStrategy(bt.Strategy):
    """带有自定义日期过滤的定时器。"""

    def __init__(self):

# 只在月末的工作日触发
        self.add_timer(
            when=time(15, 0),  # 下午 3 点
            allow=self._is_eom,
        )

    def _is_eom(self, date):
        """检查日期是否是月末。"""
        next_day = date + timedelta(days=1)
        return date.month != next_day.month

    def notify_timer(self, timer, when, *args, **kwargs):
        print(f'月末定时器在 {when} 触发')

```

### Timer 的常见应用场景

#### 场景 1：收盘前平仓

```python
class CloseAtEndStrategy(bt.Strategy):
    """在收盘前平仓。"""

    def __init__(self):

# 收盘前 5 分钟触发
        self.add_timer(
            when=time(14, 55),
            weekdays=[0, 1, 2, 3, 4],
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        """平掉所有持仓。"""
        self.close()

```

#### 场景 2：定期检查仓位

```python
class PositionCheckStrategy(bt.Strategy):
    """定期检查仓位状态。"""

    def __init__(self):
        self.add_timer(
            when=bt.Timer.SESSION_START,
            repeat=timedelta(hours=1),
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        """每小时检查一次仓位。"""
        position = self.getposition()
        print(f'时间: {when}, 持仓: {position.size}, 成本: {position.price}')

```

#### 场景 3：开盘下单

```python
class OpenOrderStrategy(bt.Strategy):
    """在开盘时下单。"""

    def __init__(self):

# cheat=True 允许在经纪商处理前执行
        self.add_timer(
            when=bt.Timer.SESSION_START,
            cheat=True,
            weekdays=[0, 1, 2, 3, 4],
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        """在开盘时使用开盘价下单。"""
        if not self.getposition():
            self.buy(size=100)

```

---
## Store API

Store API 提供了连接外部数据源和经纪商的统一接口。Store 管理连接、处理身份验证，并提供数据馈送和经纪商实例。

### Store 基类

```python
class backtrader.Store

```
所有 Store 实现的基类。Store 通常实现单例模式，以便在数据馈送和经纪商之间共享连接。

#### 类属性

| 属性 | 描述 |

|------|------|

| `BrokerCls` | 与此 store 关联的经纪商类 |

| `DataCls` | 与此 store 关联的数据馈送类 |

| `_started` | Store 是否已启动 |

| `params` | 参数定义元组 |

#### 方法

##### getdata()

```python
def getdata(self, *args, **kwargs)

```
创建与此 store 关联的数据馈送。

- *返回值：** 连接到此 store 的数据馈送实例

##### getbroker()

```python
@classmethod
def getbroker(cls, *args, **kwargs)

```
创建与此 store 关联的经纪商。

- *返回值：** 连接到此 store 的经纪商实例

##### start()

```python
def start(self, data=None, broker=None)

```
启动 store 并初始化连接。

##### stop()

```python
def stop(self)

```
停止 store 并清理资源。

##### put_notification()

```python
def put_notification(self, msg, *args, **kwargs)

```
向通知队列添加消息。

##### get_notifications()

```python
def get_notifications(self)

```
返回待处理的 store 通知。

### 可用的 Store 实现

#### CCXTStore - 加密货币交易所

```python
import backtrader as bt

# 为加密货币交易所创建 store

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'your_api_key',
        'secret': 'your_secret',
        'enableRateLimit': True,
    },
    retries=3,
    sandbox=False,
)

# 获取数据馈送

data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
)

# 获取经纪商

broker = store.getbroker()
cerebro.setbroker(broker)

```

- *CCXTStore 参数：**

| 参数 | 描述 |

|------|------|

| `exchange` | 交易所 ID（如 'binance'、'okx'） |

| `currency` | 余额的基础货币 |

| `config` | 包含 API 密钥的交易所配置字典 |

| `retries` | 重试次数 |

| `debug` | 启用调试输出 |

| `sandbox` | 使用交易所沙盒/测试网 |

| `use_rate_limiter` | 启用智能速率限制 |

| `use_connection_manager` | 启用自动重连 |

- *CCXTStore 方法：**

```python

# 获取钱包余额

balance = store.get_wallet_balance(params=None)

# 获取 OHLCV 数据

ohlcv = store.fetch_ohlcv(
    symbol='BTC/USDT',
    timeframe='1h',
    since=timestamp,
    limit=100
)

# 创建订单

order = store.create_order(
    symbol='BTC/USDT',
    order_type='limit',
    side='buy',
    amount=0.001,
    price=50000,
    params={}
)

# 取消订单

store.cancel_order(order_id, 'BTC/USDT')

# 检查连接

if store.is_connected():
    print("已连接到交易所")

```

#### CTPStore - 中国期货市场

```python
import backtrader as bt

# 为中国期货创建 CTP store

store = bt.stores.CTPStore(
    ctp_setting={
        'td_front': 'tcp://180.168.146.187:10130',
        'md_front': 'tcp://180.168.146.187:10131',
        'broker_id': '9999',
        'user_id': 'your_id',
        'password': 'your_password',
        'app_id': 'simnow_client_test',
        'auth_code': '0000000000000000',
    }
)

# 获取数据馈送

data = store.getdata(
    dataname='rb2501.SHFE',
    timeframe=bt.TimeFrame.Minutes,
)

# 获取经纪商

broker = store.getbroker()

```

- *CTPStore 功能：**

- 管理交易和行情两个连接
- 处理订单提交和取消
- 提供账户和持仓查询
- 向数据馈送分发 tick 数据
- 支持带回调的自动重连

- *CTPStore 方法：**

```python

# 发送订单

order_ref = store.send_order(
    symbol='rb2501.SHFE',
    direction='0',  # 0=买入，1=卖出
    offset='0',     # 0=开仓，1=平仓，3=平今
    price=3500.0,
    volume=1
)

# 取消订单

store.cancel_order(
    symbol='rb2501.SHFE',
    order_ref=order_ref,
    front_id=front_id,
    session_id=session_id
)

# 获取余额

store.get_balance()
cash = store.get_cash()
value = store.get_value()

# 获取持仓

positions = store.get_positions()

# 注册回调

store.on_disconnect(lambda reason: print(f'断开连接: {reason}'))
store.on_reconnect(lambda: print('已重新连接'))

# 检查连接

if store.is_connected:
    print("已连接到 CTP")

```

#### IBStore - Interactive Brokers

```python
import backtrader as bt

# 创建 IB store

store = bt.stores.IBStore(
    host='127.0.0.1',
    port=7497,  # 生产环境 7496，模拟交易 7497
    clientId=1,
    notifyall=False,
    reconnect=3,
    timeout=3.0,
)

# 获取数据馈送

data = store.getdata(
    dataname='AAPL',
    what='rtbar',  # 'rtbar' 用于实时数据

)

# 获取经纪商

broker = store.getbroker()

```

- *IBStore 参数：**

| 参数 | 默认值 | 描述 |

|------|--------|------|

| `host` | '127.0.0.1' | IB TWS/网关主机 |

| `port` | 7496 | 连接端口（模拟交易用 7497） |

| `clientId` | None | 客户端 ID（None 则随机） |

| `notifyall` | False | 通知所有消息还是仅错误 |

| `reconnect` | 3 | 重连次数（-1 表示无限） |

| `timeout` | 3.0 | 连接超时 |

### Store 集成模式

#### 模式 1：单个 Store，多个数据馈送

```python
import backtrader as bt

# 创建一个 store 用于共享连接

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={'apiKey': 'xxx', 'secret': 'xxx'}
)

cerebro = bt.Cerebro()

# 使用同一 store 连接添加多个数据馈送

cerebro.adddata(store.getdata(dataname='BTC/USDT'))
cerebro.adddata(store.getdata(dataname='ETH/USDT'))
cerebro.adddata(store.getdata(dataname='BNB/USDT'))

# 从 store 设置经纪商

cerebro.setbroker(store.getbroker())

results = cerebro.run()

```

#### 模式 2：Store 与自定义数据馈送

```python
import backtrader as bt

class CustomCCXTFeed(bt.feeds.CCXTFeed):
    """带有额外处理的自定义数据馈送。"""

    params = (
        ('drop_new', True),  # 丢弃不完整的 K 线
        ('historical', True),  # 获取历史数据
    )

# 使用 store 与自定义馈送

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={'apiKey': 'xxx', 'secret': 'xxx'}
)

data = CustomCCXTFeed(
    store=store,
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=15
)

```

#### 模式 3：Store 通知

```python
import backtrader as bt

class NotificationStrategy(bt.Strategy):
    """响应 store 通知的策略。"""

    def notify_store(self, msg, *args, **kwargs):
        """处理 store 通知。"""
        if msg == 'DISCONNECTED':
            print('Store 断开连接！')

# 采取措施：平仓、停止交易等
        elif msg == 'CONNECTED':
            print('Store 重新连接！')
        elif msg == 'ERROR':
            print(f'Store 错误: {args}')

# Store 将向策略发送通知

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={'apiKey': 'xxx', 'secret': 'xxx'}
)

cerebro = bt.Cerebro()
cerebro.addstrategy(NotificationStrategy)
cerebro.setbroker(store.getbroker())

```

#### 模式 4：Store 连接监控

```python
import backtrader as bt

class MonitoredStrategy(bt.Strategy):
    """带有连接监控的策略。"""

    def __init__(self):
        self.store = self.broker.store
        self._setup_monitoring()

    def _setup_monitoring(self):
        """设置连接监控回调。"""
        if hasattr(self.store, 'on_disconnect'):
            self.store.on_disconnect(self._on_disconnect)
        if hasattr(self.store, 'on_reconnect'):
            self.store.on_reconnect(self._on_reconnect)

    def _on_disconnect(self, reason):
        print(f'连接丢失: {reason}')

    def _on_reconnect(self):
        print('连接已恢复')

    def next(self):

# 交易前检查连接
        if hasattr(self.store, 'is_connected'):
            if not self.store.is_connected:
                return  # 跳过交易逻辑

# 常规交易逻辑

```

### Store 最佳实践

1. **每个交易所使用单个 Store**
   - 为每个交易所/经纪商创建一个 store 实例
   - 在数据馈送和经纪商之间共享 store
   - 这可以减少连接开销并确保状态一致

1. **处理重连**
   - 实现断开连接/重新连接回调
   - 在断开连接期间暂停交易
   - 重新连接后重新同步状态

1. **速率限制**
   - 在可用时使用内置的速率限制器
   - 遵守交易所的速率限制
   - 使用指数退避实现重试逻辑

1. **错误处理**
   - 在策略中实现 `notify_store()`
   - 记录错误以便调试
   - 在服务不可用时优雅降级

1. **资源清理**
   - 完成后调用 `store.stop()`
   - 在适用的地方使用上下文管理器
   - 确保线程正确终止

---
## 综合示例

| API | 用途 | 核心类 |

|-----|------|--------|

| **Signal**| 基于指标的声明式交易 | `Signal`、`SignalStrategy` |

|**Timer**| 基于时间的事件调度 | `Timer`、`Strategy.add_timer()` |

|**Store** | 外部数据/经纪商连接 | `Store`、`CCXTStore`、`CTPStore`、`IBStore` |

这些 API 可以协同工作创建复杂的交易系统：

```python
import backtrader as bt
from datetime import time, timedelta

class AdvancedStrategy(bt.SignalStrategy):
    """结合信号、定时器和 store 连接的策略。"""

    params = (
        ('exit_time', time(15, 0)),  # 下午 3 点平仓
    )

    def __init__(self):
        super().__init__()

# 基于信号的入场
        sma_fast = bt.indicators.SMA(period=10)
        sma_slow = bt.indicators.SMA(period=30)
        sma_cross = bt.ind.CrossOver(sma_fast, sma_slow)
        self.signal_add(bt.SIGNAL_LONGSHORT, sma_cross)

# 基于时间的出场
        self.add_timer(
            when=self.p.exit_time,
            weekdays=[0, 1, 2, 3, 4],
        )

# 实时交易的 store 引用
        self.store = self.broker.store if hasattr(self.broker, 'store') else None

    def notify_timer(self, timer, when, *args, **kwargs):
        """收盘时退出持仓。"""
        self.close()

    def notify_store(self, msg, *args, **kwargs):
        """处理 store 通知。"""
        if msg == 'DISCONNECTED':
            print('警告：与交易所断开连接')

# 可以在这里执行额外的错误处理

# 完整的使用示例

def run_advanced_strategy():
    cerebro = bt.Cerebro()

# 创建加密货币交易所 store
    store = bt.stores.CCXTStore(
        exchange='binance',
        currency='USDT',
        config={
            'apiKey': 'your_api_key',
            'secret': 'your_secret',
        },
        sandbox=True,  # 使用测试网
    )

# 添加数据
    data = store.getdata(
        dataname='BTC/USDT',
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
    )
    cerebro.adddata(data)

# 设置经纪商
    cerebro.setbroker(store.getbroker())

# 添加策略
    cerebro.addstrategy(AdvancedStrategy)

# 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

# 运行
    results = cerebro.run()
    strat = results[0]

# 打印结果
    print(f'夏普比率: {strat.analyzers.sharpe.get_analysis()}')
    print(f'回撤: {strat.analyzers.drawdown.get_analysis()}')

    return results

```

---
## API 快速参考

### Signal API 快速参考

| 方法/类 | 描述 |

|---------|------|

| `bt.Signal(data)` | 从数据线创建信号指标 |

| `bt.SignalStrategy` | 自动执行信号的策略基类 |

| `signal_add(sigtype, signal)` | 向策略添加信号 |

| `cerebro.add_signal(sigtype, sigcls, ...)` | 通过 cerebro 添加信号 |

### Timer API 快速参考

| 方法/类 | 描述 |

|---------|------|

| `bt.Timer.SESSION_START` | 会话开始常量 |

| `bt.Timer.SESSION_END` | 会话结束常量 |

| `add_timer(when, ...)` | 向策略添加定时器 |

| `notify_timer(timer, when, ...)` | 接收定时器通知 |

### Store API 快速参考

| 方法/类 | 描述 |

|---------|------|

| `bt.stores.CCXTStore(...)` | 加密货币交易所 store |

| `bt.stores.CTPStore(...)` | 中国期货 store |

| `bt.stores.IBStore(...)` | Interactive Brokers store |

| `store.getdata(...)` | 从 store 获取数据馈送 |

| `store.getbroker(...)` | 从 store 获取经纪商 |

| `store.start()` / `store.stop()` | 启动/停止 store |

---
## 相关文档

- [Cerebro API 参考](cerebro_zh.md) - 核心引擎 API
- [Strategy API 参考](strategy_zh.md) - 策略开发指南
- [Data Feeds API 参考](data-feeds_zh.md) - 数据源详细说明
- [Broker API 参考](broker_zh.md) - 订单执行和持仓管理
