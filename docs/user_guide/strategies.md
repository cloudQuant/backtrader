# 策略开发指南

本指南将帮助你掌握 Backtrader 策略开发的核心概念和最佳实践。

## 策略基础

### 策略类结构

每个策略都必须继承自 `bt.Strategy` 类：

```python
import backtrader as bt

class MyStrategy(bt.Strategy):
    # 策略参数
    params = (
        ('param1', 20),
        ('param2', 10),
    )

    def __init__(self):
        # 初始化代码

    def next(self):
        # 核心交易逻辑
```

### 核心方法

1. **__init__(self)**
   - 策略初始化
   - 创建指标
   - 设置变量

2. **next(self)**
   - 主要交易逻辑
   - 每个 bar 都会调用
   - 处理订单和持仓

3. **notify_order(self, order)**
   - 订单状态通知
   - 处理订单执行结果

4. **notify_trade(self, trade)**
   - 交易状态通知
   - 处理开仓/平仓信息

## 策略开发流程

### 1. 数据准备

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        # 获取数据
        self.data = self.datas[0]
        # 访问数据
        self.close = self.data.close
        self.high = self.data.high
        self.low = self.data.low
```

### 2. 指标计算

```python
def __init__(self):
    # 创建技术指标
    self.sma = bt.indicators.SimpleMovingAverage(
        self.data.close, period=self.params.period
    )
    self.rsi = bt.indicators.RSI(
        self.data.close, period=14
    )
```

### 3. 交易逻辑

```python
def next(self):
    # 没有持仓
    if not self.position:
        # 买入条件
        if self.sma > self.data.close and self.rsi < 30:
            self.buy()
    # 有持仓
    else:
        # 卖出条件
        if self.sma < self.data.close or self.rsi > 70:
            self.sell()
```

### 4. 订单管理

```python
def notify_order(self, order):
    if order.status in [order.Submitted, order.Accepted]:
        return

    if order.status in [order.Completed]:
        if order.isbuy():
            self.log(f'买入执行: {order.executed.price:.2f}')
        elif order.issell():
            self.log(f'卖出执行: {order.executed.price:.2f}')

    elif order.status in [order.Canceled, order.Margin, order.Rejected]:
        self.log('订单取消/保证金不足/拒绝')
```

## 进阶技巧

### 1. 多数据源策略

```python
class MultiDataStrategy(bt.Strategy):
    def __init__(self):
        self.stock = self.datas[0]
        self.index = self.datas[1]

    def next(self):
        if self.stock.close[0] > self.stock.close[-1] and \
           self.index.close[0] > self.index.close[-1]:
            self.buy(data=self.stock)
```

### 2. 参数优化

```python
class OptStrategy(bt.Strategy):
    params = (
        ('period', 20),
        ('devfactor', 2),
    )

    def __init__(self):
        self.bband = bt.indicators.BollingerBands(
            period=self.p.period,
            devfactor=self.p.devfactor
        )
```

### 3. 持仓管理

```python
def next(self):
    # 计算目标持仓
    target_size = self.broker.get_cash() / self.data.close[0]
    
    # 调整持仓
    if target_size > self.position.size:
        self.buy(size=target_size - self.position.size)
    elif target_size < self.position.size:
        self.sell(size=self.position.size - target_size)
```

### 4. 风险管理

```python
def __init__(self):
    # 跟踪止损
    self.trailing_stop = bt.indicators.Highest(
        self.data.close, period=20
    )

def next(self):
    if self.position and \
       self.data.close[0] < self.trailing_stop[0] * 0.95:
        self.close()  # 平仓
```

## 最佳实践

### 1. 代码组织

```python
class WellStructuredStrategy(bt.Strategy):
    def __init__(self):
        self._initialize_indicators()
        self._initialize_trading_variables()

    def _initialize_indicators(self):
        self.sma = bt.indicators.SMA(period=20)
        self.rsi = bt.indicators.RSI(period=14)

    def _initialize_trading_variables(self):
        self.last_trade = None
        self.trades_count = 0
```

### 2. 日志记录

```python
def log(self, txt, dt=None):
    dt = dt or self.datas[0].datetime.date(0)
    print(f'{dt.isoformat()} {txt}')

def notify_trade(self, trade):
    if trade.isclosed:
        self.log(f'交易利润: {trade.pnl:.2f}')
```

### 3. 健壮性检查

```python
def next(self):
    # 检查数据是否有效
    if not self.data.close[0] or not self.sma[0]:
        return

    # 检查是否有足够资金
    if self.broker.get_cash() < 5000:
        return
```

### 4. 性能优化

```python
def __init__(self):
    # 缓存常用值
    self.order = None
    self.price = self.data.close
    self.volume = self.data.volume

def next(self):
    # 使用缓存值
    price = self.price[0]
    volume = self.volume[0]
```

## 常见问题

1. **策略不交易**
   - 检查交易条件
   - 验证资金是否充足
   - 确认订单状态

2. **回测结果不理想**
   - 检查交易逻辑
   - 优化参数设置
   - 考虑交易成本

3. **执行速度慢**
   - 减少指标计算
   - 优化数据处理
   - 使用缓存机制

## 下一步

- 学习[数据源](./data_feeds.md)使用
- 了解[指标系统](./indicators.md)
- 探索[参数优化](./optimization.md)
- 研究[风险管理](../advanced/risk_mgmt.md)
