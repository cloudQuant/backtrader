---
title: 观察器 API
description: 完整的观察器类 API 参考文档
---

# 观察器 API

`Observer` 类是用于监控策略执行和在回测期间收集数据的基类。观察器跟踪现金、价值、回撤、交易和其他绩效指标等指标。

与生成信号的指标不同，观察器主要用于记录和可视化策略状态。

## 类定义

```python
class backtrader.Observer:
    """监控策略执行的基类。"""
```

## 核心属性

### `csv`

是否将观察器数据保存到 CSV 文件（默认：`True`）。

```python
class MyObserver(bt.Observer):
    csv = True  # 包含在 CSV 输出中
```

### `plotinfo`

绘图配置字典。

```python
plotinfo = dict(
    plot=True,       # 是否绘制此观察器
    subplot=True,    # 是否使用单独的子图
    plotname='',     # 图例中的名称
)
```

### `plotlines`

特定线条的绘图设置。

```python
plotlines = dict(
    line1=dict(color='blue', linewidth=2),
    line2=dict(_plotskip=True),  # 跳过绘制此线条
)
```

### `_stclock`

控制时钟同步。当为 `True` 时，观察器使用策略范围的时钟（默认：`False`）。

### `_ltype`

线迭代器类型。对于观察器，设置为 `LineIterator.ObsType`（值：2）。

## 核心方法

### `__init__(self)`

在观察器初始化期间调用。初始化跟踪变量，并在需要时添加分析器。

```python
def __init__(self):
    super().__init__()
    self._analyzers = list()
    # 初始化跟踪变量
    self.peak = float('-inf')
```

### `start(self)`

在回测运行开始时调用。

```python
def start(self):
    # 在数据处理之前执行初始化
    self.initial_value = self._owner.broker.getvalue()
```

### `_start(self)`

内部方法，确保在调用 `start()` 之前设置了所有者。

### `prenext(self)`

在达到最小周期之前对每个 bar 调用。默认情况下，观察器在 prenext 期间调用 `next()`，以便从一开始跟踪所有 bar。

```python
def prenext(self):
    self.next()  # 默认行为 - 处理每个 bar
```

### `next(self)`

对每个 bar 调用。包含更新观察器值的主要逻辑。

```python
def next(self):
    self.lines.cash[0] = self._owner.broker.getcash()
```

### `stop(self)`

回测结束后调用。

### `_register_analyzer(self, analyzer)`

向此观察器注册一个分析器。

## 线条系统

观察器使用与指标相同的线条系统：

```python
class MyObserver(bt.Observer):
    lines = ('metric1', 'metric2')

    def next(self):
        self.lines.metric1[0] = calculate_metric1()
        self.lines.metric2[0] = calculate_metric2()
```

## 内置观察器

### 经纪商观察器

#### Cash

跟踪经纪商中的当前现金金额。

```python
cerebro.addobserver(bt.observers.Cash)
```

**线条**: `cash`

#### Value

跟踪包括现金在内的投资组合价值。

```python
cerebro.addobserver(bt.observers.Value)
```

**参数**:
- `fund`（默认：`None`）- 使用基金价值而非总价值

**线条**: `value`

#### Broker

组合 Cash 和 Value 观察器。

```python
cerebro.addobserver(bt.observers.Broker)
```

**参数**:
- `fund`（默认：`None`）- 使用基金模式

**线条**: `cash`, `value`

#### FundValue

跟踪类似基金的价值。

**线条**: `fundval`

#### FundShares

跟踪类似基金的份额。

**线条**: `fundshares`

### 回撤观察器

#### DrawDown

跟踪当前和最大回撤水平。

```python
cerebro.addobserver(bt.observers.DrawDown)
```

**参数**:
- `fund`（默认：`None`）- 使用基金模式计算收益

**线条**:
- `drawdown` - 当前回撤百分比（绘制）
- `maxdrawdown` - 最大回撤（不绘制）

```python
class DrawDown(Observer):
    _stclock = True
    lines = ('drawdown', 'maxdrawdown')
    plotlines = dict(maxdrawdown=dict(_plotskip=True))
```

#### DrawDownLength

跟踪当前回撤长度和最大长度。

**线条**:
- `len` - 当前回撤长度
- `maxlen` - 最大回撤长度

### 交易观察器

#### Trades

跟踪已完成的交易并在交易关闭时绘制盈亏。

```python
cerebro.addobserver(bt.observers.Trades)
```

**参数**:
- `pnlcomm`（默认：`True`）- 显示扣除佣金后的净盈亏

**线条**:
- `pnlplus` - 正盈亏值（蓝色标记）
- `pnlminus` - 负盈亏值（红色标记）

```python
# Trades 观察器跟踪：
# - 总交易计数
# - 多头/空头交易计数
# - 胜/负统计
# - 交易长度统计
```

#### DataTrades

分别跟踪多个数据源的盈亏。

**参数**:
- `usenames`（默认：`True`）- 使用数据名称作为标签

### BuySell 观察器

在图表上可视化买卖订单。

```python
cerebro.addobserver(bt.observers.BuySell)
```

**参数**:
- `barplot`（默认：`False`）- 在 bar 极值处绘制信号
- `bardist`（默认：`0.015`）- 距离高低点的距离（1.5%）

**线条**:
- `buy` - 买入标记（绿色向上三角形）
- `sell` - 卖出标记（红色向下三角形）

```python
# 自定义标记外观
cerebro.addobserver(bt.observers.BuySell, barplot=True, bardist=0.02)
```

### 收益观察器

#### TimeReturn

跟踪随时间段变化的策略收益。

```python
cerebro.addobserver(bt.observers.TimeReturn, timeframe=bt.TimeFrame.Days)
```

**参数**:
- `timeframe`（默认：`None`）- 时间聚合周期
- `compression`（默认：`None`）- 日内时间框架的压缩
- `fund`（默认：`None`）- 使用基金模式

**线条**: `timereturn`

```python
# 跟踪每日收益
cerebro.addobserver(bt.observers.TimeReturn, timeframe=bt.TimeFrame.Days)

# 跟踪每周收益
cerebro.addobserver(bt.observers.TimeReturn, timeframe=bt.TimeFrame.Weeks)
```

#### LogReturns

跟踪策略的对数收益。

```python
cerebro.addobserver(bt.observers.LogReturns)
```

**参数**:
- `timeframe`（默认：`None`）- 时间聚合周期
- `compression`（默认：`None`）- 日内时间框架的压缩
- `fund`（默认：`None`）- 使用基金模式

**线条**: `logret1`

#### LogReturns2

扩展 LogReturns 以显示两个工具。

**线条**: `logret1`, `logret2`

### Benchmark 观察器

将策略收益与参考资产进行比较。

```python
data = bt.feeds.GenericCSVData(dataname='benchmark.csv')
cerebro.adddata(data)
cerebro.addobserver(bt.observers.Benchmark, data=data)
```

**参数**:
- `data`（默认：`None`）- 参考数据源
- `_doprenext`（默认：`False`）- 从数据开始时跟踪
- `firstopen`（默认：`False`）- 使用开盘价进行第一次比较
- `fund`（默认：`None`）- 使用基金模式

**线条**: `benchmark`

### TradeLogger

全面的日志记录观察器，用于所有交易活动。

```python
cerebro.addobserver(bt.observers.TradeLogger,
                    log_dir='./logs',
                    log_orders=True,
                    log_trades=True,
                    log_positions=True,
                    log_indicators=True,
                    log_signals=True)
```

**参数**:
- `log_dir`（默认：`'./logs'`）- 日志文件目录
- `log_orders`（默认：`True`）- 记录订单状态变化
- `log_trades`（默认：`True`）- 记录交易开仓/平仓
- `log_positions`（默认：`True`）- 每个 bar 记录持仓
- `log_indicators`（默认：`True`）- 每个 bar 记录指标值
- `log_signals`（默认：`True`）- 记录买卖信号
- `log_position_snapshot`（默认：`True`）- 将持仓快照保存为 YAML
- `snapshot_file`（默认：`'current_position.yaml'`）- 快照文件名
- `log_format`（默认：`'json'`）- 日志格式（'json' 或 'text'）
- `log_to_console`（默认：`False`）- 同时打印到控制台
- `mysql_enabled`（默认：`False`）- 启用 MySQL 日志记录
- `mysql_host`（默认：`'localhost'`）- MySQL 主机
- `mysql_port`（默认：`3306`）- MySQL 端口
- `mysql_user`（默认：`'root'`）- MySQL 用户
- `mysql_password`（默认：`''`）- MySQL 密码
- `mysql_database`（默认：`'backtrader'`）- MySQL 数据库

**生成的文件**:
- `order.log` - 订单状态变化
- `trade.log` - 交易开仓和平仓
- `position.log` - 每个 bar 的持仓值
- `indicator.log` - 每个 bar 的指标值
- `signal.log` - 买卖信号
- `current_position.yaml` - 持仓快照

## 自定义观察器开发

### 基本观察器

```python
import backtrader as bt

class CustomMetric(bt.Observer):
    """
    跟踪自定义指标的观察器。
    """
    _stclock = True  # 使用策略时钟

    lines = ('custom_value',)

    params = (
        ('period', 20),
    )

    plotinfo = dict(
        plot=True,
        subplot=True,
        plotname='自定义指标',
    )

    def __init__(self):
        super().__init__()
        self.high_watermark = float('-inf')

    def next(self):
        # 计算自定义指标
        value = self._owner.broker.getvalue()

        # 跟踪历史最高点
        if value > self.high_watermark:
            self.high_watermark = value

        # 存储到线条中
        self.lines.custom_value[0] = value - self.high_watermark
```

### 使用分析器的观察器

```python
class SharpeRatioObserver(bt.Observer):
    """
    使用分析器跟踪夏普比率的观察器。
    """
    _stclock = True

    lines = ('sharpe',)

    params = (
        ('period', 252),  # 年化周期
        ('riskfreerate', 0.0),
    )

    plotinfo = dict(plot=True, subplot=True)

    def __init__(self):
        super().__init__()
        # 将分析器添加为从属
        self._sharpe = self._owner._addanalyzer_slave(
            bt.analyzers.SharpeRatio,
            period=self.p.period,
            riskfreerate=self.p.riskfreerate
        )

    def next(self):
        # 从分析器获取当前夏普比率
        if hasattr(self._sharpe, 'rets') and self._sharpe.rets:
            self.lines.sharpe[0] = self._sharpe.rets.get('sharperatio', float('NaN'))
```

### 多线条观察器

```python
class PortfolioStats(bt.Observer):
    """
    跟踪多个投资组合统计指标的观察器。
    """
    _stclock = True

    lines = (
        'exposure',      # 敞口
        'leverage',      # 杠杆
        'cash_ratio',    # 现金比例
    )

    plotinfo = dict(plot=True, subplot=True)

    plotlines = dict(
        exposure=dict(color='blue'),
        leverage=dict(color='orange'),
        cash_ratio=dict(color='green'),
    )

    def next(self):
        portfolio_value = self._owner.broker.getvalue()
        cash = self._owner.broker.getcash()

        # 计算指标
        self.lines.cash_ratio[0] = cash / portfolio_value if portfolio_value else 0
        self.lines.exposure[0] = 1 - self.lines.cash_ratio[0]

        # 计算杠杆（总持仓价值 / 投资组合价值）
        total_position = 0
        for data in self._owner.datas:
            position = self._owner.getposition(data)
            total_position += abs(position.size) * data.close[0]

        self.lines.leverage[0] = total_position / portfolio_value if portfolio_value else 0
```

## 注册流程

观察器通过 `cerebro.addobserver()` 添加时自动注册：

```python
# 观察器注册
cerebro.addobserver(bt.observers.DrawDown)

# 带参数
cerebro.addobserver(bt.observers.DrawDown, fund=True)

# 多个实例
cerebro.addobserver(bt.observers.DrawDown)
cerebro.addobserver(bt.observers.Trades)
```

注册流程：
1. 创建观察器实例
2. `_ltype` 设置为 `LineIterator.ObsType`（2）
3. 观察器被添加到策略的 `_lineiterators[ObsType]` 列表
4. 执行期间调用 `prenext()`、`next()`、`stop()`

## 观察器 vs 指标

| 特性 | 观察器 | 指标 |
|------|--------|------|
| 用途 | 监控和记录 | 生成信号 |
| `_ltype` | `ObsType` (2) | `IndType` (0) |
| `_stclock` | 通常为 `True` | 通常为 `False` |
| 默认 `prenext` | 调用 `next()` | 不执行任何操作 |
| 绘图 | 默认使用子图 | 叠加在数据上 |
| 线条计算 | 外部（经纪商/交易） | 内部计算 |

## 绘图配置

### 禁用绘图

```python
# 单个观察器
cerebro.addobserver(bt.observers.DrawDown, _plot=False)

# 或修改 plotinfo
class MyObserver(bt.Observer):
    plotinfo = dict(plot=False)
```

### 子图配置

```python
class MyObserver(bt.Observer):
    plotinfo = dict(
        plot=True,
        subplot=True,      # 单独子图
        plotlinelabels=True,
        plotymargin=0.10,  # Y轴边距
        plothlines=[0.0],  # 水平线
    )
```

### 线条样式

```python
class MyObserver(bt.Observer):
    plotlines = dict(
        metric1=dict(
            color='blue',
            linewidth=2,
            linestyle='-',
            marker='o',
            markersize=4,
        ),
        metric2=dict(
            color='red',
            _plotskip=True,  # 不绘制
        ),
    )
```

## 完整示例

```python
import backtrader as bt

class MyStrategy(bt.Strategy):
    params = (
        ('sma_period', 20),
    )

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.sma_period)

    def next(self):
        if not self.position:
            if self.data.close[0] > self.sma[0]:
                self.buy()
        else:
            if self.data.close[0] < self.sma[0]:
                self.sell()

# 创建 cerebro
cerebro = bt.Cerebro()

# 添加策略
cerebro.addstrategy(MyStrategy)

# 添加数据
data = bt.feeds.YahooFinanceData(dataname='AAPL', fromdate='2020-01-01', todate='2023-12-31')
cerebro.adddata(data)

# 添加观察器
cerebro.addobserver(bt.observers.Broker)        # 现金和价值
cerebro.addobserver(bt.observers.DrawDown)      # 回撤跟踪
cerebro.addobserver(bt.observers.Trades)        # 交易盈亏
cerebro.addobserver(bt.observers.BuySell)       # 买卖标记

# 添加自定义观察器
class PositionSize(bt.Observer):
    _stclock = True
    lines = ('possize',)
    plotinfo = dict(plot=True, subplot=True, plotname='持仓数量')

    def next(self):
        self.lines.possize[0] = self._owner.getposition().size

cerebro.addobserver(PositionSize)

# 运行
cerebro.run()

# 绘图
cerebro.plot()
```

## 下一步

- [策略 API](strategy_zh.md) - 策略开发
- [分析器 API](analyzer_zh.md) - 绩效分析
- [指标 API](indicator_zh.md) - 自定义指标
