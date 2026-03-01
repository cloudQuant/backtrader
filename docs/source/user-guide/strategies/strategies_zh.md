---
title: 交易策略
description: 构建有效的交易策略
---

# 交易策略

策略包含您的交易逻辑和决策规则。本指南涵盖策略开发模式和最佳实践。

## 策略模板

```python
class MyStrategy(bt.Strategy):
    """
    策略描述。

    参数:
        param1: 参数说明
        param2: 参数说明
    """

    params = (
        ('param1', 20),
        ('param2', 0.5),
    )

    def __init__(self):
        """
        初始化指标和计算。
        在回测开始前调用一次。
        """
        # 您的初始化代码
        pass

    def next(self):
        """
        每根K线调用。
        包含您的交易逻辑。
        """
        # 您的交易逻辑
        pass
```

## 订单管理

### 市价单

```python
class MyStrategy(bt.Strategy):
    def next(self):
        # 买入默认数量
        self.buy()

        # 买入指定数量
        self.buy(size=100)

        # 卖出全部持仓
        self.sell()

        # 平仓
        self.close()

        # 买入可用资金的百分比
        self.buy(size=0.5)  # 50% 的资金
```

### 限价单

```python
class MyStrategy(bt.Strategy):
    def next(self):
        # 以指定价格或更好价格买入
        order = self.buy(price=100.0)

        # 限价卖出
        order = self.sell(limit=105.0)

        # 止损单
        order = self.sell(stop=95.0)

        # 止损限价单
        order = self.sell(stop=95.0, limit=94.5)
```

### 订单跟踪

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.order = None

    def next(self):
        # 只在没有待处理订单时下单
        if self.order:
            return

        # 下单并保存引用
        self.order = self.buy()

    def notify_order(self, order):
        """订单状态变化时调用。"""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'买入成交, 价格: {order.executed.price:.2f}')
            else:
                self.log(f'卖出成交, 价格: {order.executed.price:.2f}')

        self.order = None  # 重置订单引用
```

## 交易通知

```python
class MyStrategy(bt.Strategy):
    def notify_trade(self, trade):
        """交易关闭时调用。"""
        if not trade.isclosed:
            return

        self.log(f'交易盈亏: {trade.pnl:.2f}, '
                f'佣金: {trade.commission:.2f}')
```

## 持仓管理

### 检查持仓

```python
class MyStrategy(bt.Strategy):
    def next(self):
        # 检查是否有持仓
        if self.position:
            self.log(f'持仓数量: {self.position.size}')
        else:
            self.log('无持仓')
```

### 仓位管理

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sizer = bt.sizers.FixedSize(stake=0.1)  # 每笔交易 10%

    def next(self):
        # 买入组合价值的 10%
        self.buy(size=self.broker.getcash() * 0.1 / self.data.close[0])
```

## 止损和止盈

```python
class MyStrategy(bt.Strategy):
    params = (
        ('stop_loss_pct', 0.02),   # 2% 止损
        ('take_profit_pct', 0.05), # 5% 止盈
    )

    def next(self):
        if not self.position:
            self.buy()
        else:
            entry_price = self.position.price
            current_price = self.data.close[0]

            # 计算止损和止盈价格
            stop_loss = entry_price * (1 - self.p.stop_loss_pct)
            take_profit = entry_price * (1 + self.p.take_profit_pct)

            # 检查是否触发止损或止盈
            if current_price <= stop_loss:
                self.sell()  # 止损

            elif current_price >= take_profit:
                self.sell()  # 止盈
```

## 多策略

```python
# 创建多个策略
cerebro = bt.Cerebro()

cerebro.addstrategy(Strategy1, period=10)
cerebro.addstrategy(Strategy2, period=20)
cerebro.addstrategy(Strategy3, period=30)

# 每个策略独立运行
```

## 基于时间的交易

```python
import datetime

class MyStrategy(bt.Strategy):
    params = (
        ('trade_start_hour', 10),
        ('trade_end_hour', 15),
    )

    def next(self):
        # 只在特定时段交易
        current_time = self.data.datetime.time(0)

        if current_time.hour < self.p.trade_start_hour:
            return  # 太早

        if current_time.hour >= self.p.trade_end_hour:
            return  # 太晚

        # 交易逻辑
        self.buy()
```

## 策略日志

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        # 启用日志
        pass

    def next(self):
        # 记录日志
        self.log(f'收盘价: {self.data.close[0]:.2f}')

    def notify_order(self, order):
        self.log(f'订单状态: {order.getstatusname()}')
```

## 策略参数优化

```python
# 定义参数范围
cerebro.optstrategy(
    MyStrategy,
    ma_period=range(10, 31, 5),      # 10, 15, 20, 25, 30
    threshold=[0.5, 1.0, 1.5]         # 0.5, 1.0, 1.5
)

# 运行优化
results = cerebro.run(maxcpu=1)  # 使用 1 个 CPU 核心

# 获取最佳结果
best_result = results[0]
print(f'最佳参数: {best_result.params._getitems()}')
```

## 常见策略模式

### 趋势跟踪

```python
class TrendFollowing(bt.Strategy):
    params = (
        ('fast_period', 10),
        ('slow_period', 30),
    )

    def __init__(self):
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)

    def next(self):
        if self.crossover > 0:
            self.buy()  # 上升趋势开始
        elif self.crossover < 0:
            self.sell()  # 下降趋势开始
```

### 均值回归

```python
class MeanReversion(bt.Strategy):
    params = (
        ('period', 20),
        ('threshold', 2),  # 标准差倍数
    )

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)
        self.stddev = bt.indicators.StdDev(self.data.close, period=self.p.period)
        self.upper_band = self.sma + self.stddev * self.p.threshold
        self.lower_band = self.sma - self.stddev * self.p.threshold

    def next(self):
        if self.data.close[0] < self.lower_band[0]:
            self.buy()  # 价格过低, 买入
        elif self.data.close[0] > self.upper_band[0]:
            self.sell()  # 价格过高, 卖出
```

### 突破

```python
class Breakout(bt.Strategy):
    params = (
        ('period', 20),
    )

    def __init__(self):
        self.high_band = bt.indicators.Highest(self.data.high, period=self.p.period)
        self.low_band = bt.indicators.Lowest(self.data.low, period=self.p.period)

    def next(self):
        if self.data.close[0] > self.high_band[-1]:
            self.buy()  # 向上突破

        elif self.data.close[0] < self.low_band[-1]:
            self.sell()  # 向下突破
```

## 下一步学习

- [分析器](analyzers_zh.md) - 评估策略性能
- [观察器](observers_zh.md) - 监控策略行为
- [绘图](plotting_zh.md) - 可视化结果
