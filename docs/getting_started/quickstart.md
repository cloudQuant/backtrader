# 快速开始

本指南将帮助你快速上手 Backtrader，创建你的第一个交易策略。

## 基本概念

Backtrader 的核心组件：
- `Cerebro`: 回测引擎，负责运行策略
- `Strategy`: 交易策略类
- `DataFeed`: 数据源
- `Indicator`: 技术指标
- `Analyzer`: 分析器

## 第一个策略

以下是一个简单的均线交叉策略示例：

```python
import backtrader as bt
import datetime

# 定义策略类
class SmaCross(bt.Strategy):
    # 策略参数
    params = (
        ('fast', 10),  # 快速均线周期
        ('slow', 30),  # 慢速均线周期
    )

    def __init__(self):
        # 计算均线
        self.sma_fast = bt.indicators.SMA(period=self.p.fast)
        self.sma_slow = bt.indicators.SMA(period=self.p.slow)
        # 生成交叉信号
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)

    def next(self):
        # 没有持仓，出现金叉时买入
        if not self.position and self.crossover > 0:
            self.buy()
        # 持有仓位，出现死叉时卖出
        elif self.position and self.crossover < 0:
            self.sell()

# 创建回测引擎
cerebro = bt.Cerebro()

# 加载数据
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',  # 股票代码
    fromdate=datetime.datetime(2020, 1, 1),
    todate=datetime.datetime(2023, 12, 31)
)
cerebro.adddata(data)

# 设置初始资金
cerebro.broker.setcash(100000.0)

# 设置交易手续费
cerebro.broker.setcommission(commission=0.001)

# 添加策略
cerebro.addstrategy(SmaCross)

# 添加分析器
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

# 运行回测
results = cerebro.run()

# 打印结果
strategy = results[0]
print(f'夏普比率: {strategy.analyzers.sharpe.get_analysis()["sharperatio"]:.2f}')
print(f'最大回撤: {strategy.analyzers.drawdown.get_analysis()["max"]["drawdown"]:.2f}%')

# 绘制结果
cerebro.plot()
```

## 运行策略

将上述代码保存为 `sma_cross.py` 并运行：

```bash
python sma_cross.py
```

## 策略说明

1. **策略类定义**
   - 继承 `bt.Strategy`
   - 定义策略参数
   - 初始化技术指标
   - 实现交易逻辑

2. **数据加载**
   - 使用内置数据源
   - 设置时间范围
   - 添加到回测引擎

3. **回测设置**
   - 设置初始资金
   - 设置交易费用
   - 添加分析器

4. **结果分析**
   - 计算性能指标
   - 绘制交易图表

## 进阶用法

1. **使用自定义数据源**
```python
class MyDataFeed(bt.feeds.PandasData):
    params = (
        ('datetime', 'date'),
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
    )
```

2. **添加自定义指标**
```python
class MyIndicator(bt.Indicator):
    lines = ('myline',)
    params = (('period', 20),)

    def next(self):
        self.lines.myline[0] = sum(self.data.close.get(size=self.p.period)) / self.p.period
```

3. **参数优化**
```python
cerebro.optstrategy(
    SmaCross,
    fast=range(5, 20, 5),
    slow=range(20, 40, 5)
)
```

## 下一步

- 学习[基本概念](../user_guide/basic_concepts.md)
- 了解[数据源](../user_guide/data_feeds.md)
- 探索[技术指标](../user_guide/indicators.md)
- 研究[参数优化](../user_guide/optimization.md)

## 常见问题

1. **数据加载失败**
   - 检查数据格式是否正确
   - 确保网络连接正常
   - 验证数据源可用性

2. **策略没有交易**
   - 检查交易条件
   - 确认资金是否充足
   - 验证数据是否正确加载

3. **回测结果异常**
   - 检查手续费设置
   - 确认订单大小合理
   - 验证指标计算正确
