# Backtrader 基本概念

本文档介绍 Backtrader 的核心概念和组件。

## 架构概览

Backtrader 的核心架构由以下组件组成：

```
Cerebro (回测引擎)
    ├── Data Feeds (数据源)
    ├── Strategies (策略)
    │   ├── Indicators (指标)
    │   └── Signals (信号)
    ├── Brokers (经纪商)
    │   ├── Orders (订单)
    │   └── Positions (持仓)
    ├── Analyzers (分析器)
    └── Writers (记录器)
```

## 核心组件

### 1. Cerebro（大脑）

Cerebro 是回测引擎的核心，负责：
- 管理数据源
- 运行策略
- 处理订单
- 执行回测
- 生成分析报告

```python
cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(MyStrategy)
cerebro.run()
```

### 2. Strategy（策略）

Strategy 是交易策略的基类，包含：
- 交易逻辑
- 指标计算
- 订单管理
- 持仓管理

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        # 初始化指标
        pass

    def next(self):
        # 交易逻辑
        pass
```

### 3. DataFeeds（数据源）

数据源提供历史数据，支持：
- CSV 文件
- 数据库
- 实时数据
- 自定义数据源

```python
data = bt.feeds.PandasData(
    dataname=df,
    datetime='date',
    open='open',
    high='high',
    low='low',
    close='close',
    volume='volume'
)
```

### 4. Indicators（指标）

技术指标用于分析市场，包括：
- 移动平均线
- 动量指标
- 波动率指标
- 自定义指标

```python
class MyIndicator(bt.Indicator):
    lines = ('myline',)
    params = (('period', 20),)

    def next(self):
        self.lines.myline[0] = self.data.close[0]
```

### 5. Broker（经纪商）

经纪商模拟真实交易环境：
- 订单执行
- 资金管理
- 手续费计算
- 滑点模拟

```python
cerebro.broker.setcash(100000.0)
cerebro.broker.setcommission(commission=0.001)
```

### 6. Analyzers（分析器）

分析器用于评估策略性能：
- 收益率
- 夏普比率
- 最大回撤
- 交易统计

```python
cerebro.addanalyzer(bt.analyzers.SharpeRatio)
cerebro.addanalyzer(bt.analyzers.DrawDown)
```

## 数据结构

### 1. Lines（数据线）

Lines 是 Backtrader 的基本数据结构：
- 时间序列数据
- 指标值
- 信号值

```python
self.data.close  # 收盘价线
self.data.high   # 最高价线
self.sma = bt.indicators.SMA()  # 均线
```

### 2. TimeFrame（时间框架）

支持多个时间周期：
- Ticks
- Minutes
- Days
- Weeks
- Months
- Years

```python
cerebro.resampledata(data, timeframe=bt.TimeFrame.Days)
```

## 执行流程

1. **初始化阶段**
   - 加载数据
   - 创建指标
   - 设置参数

2. **预热阶段**
   - 计算指标
   - 等待足够数据

3. **交易阶段**
   - 执行策略
   - 处理订单
   - 更新持仓

4. **分析阶段**
   - 计算绩效
   - 生成报告
   - 绘制图表

## 最佳实践

1. **数据管理**
   - 使用正确的时间格式
   - 处理缺失数据
   - 验证数据质量

2. **策略开发**
   - 模块化设计
   - 参数优化
   - 健壮性测试

3. **风险控制**
   - 设置止损
   - 控制仓位
   - 监控风险

4. **性能优化**
   - 使用 Cython
   - 并行计算
   - 内存管理

## 下一步

- 学习[策略开发](./strategies.md)
- 了解[数据源](./data_feeds.md)
- 探索[指标系统](./indicators.md)
- 研究[参数优化](./optimization.md)
