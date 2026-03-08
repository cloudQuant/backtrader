---
title: Indicator API 指标
description: 完整的 Indicator 类 API 参考，用于自定义技术指标

---
# Indicator API 指标

`Indicator` 类是 Backtrader 中所有技术指标的基类。它为创建自定义指标提供基础，管理线条数据、最小周期、计算逻辑以及与策略执行流程的自动集成。

## 类定义

```python
class backtrader.Indicator(IndicatorBase):
    """所有技术指标的基类。"""

```

## 核心属性

### `lines`

定义指标输出线的元组。

```python
class MyIndicator(bt.Indicator):
    lines = ('value1', 'value2',)

```

### `params`

指标参数定义元组。

```python
class MyIndicator(bt.Indicator):
    params = (
        ('period', 20),
        ('multiplier', 2.0),
    )

```
通过 `self.p.parameter_name` 或 `self.params.parameter_name` 访问参数。

### `alias`

指标的别名（可选）。

```python
class MyIndicator(bt.Indicator):
    alias = ('MyInd', 'CustomIndicator',)

```

### `_mindatas`

所需数据源的最小数量（默认值：1）。

```python
class MyIndicator(bt.Indicator):
    _mindatas = 2  # 需要 2 个数据源

```

### `plotinfo` / `plotlines`

指标的绘图配置。

```python
class MyIndicator(bt.Indicator):
    plotinfo = dict(subplot=False)  # 在主图上绘制
    plotlines = dict(
        value1=dict(color='blue'),
        value2=dict(ls='--'),
    )

```

## 核心方法

### `__init__(self)`

创建指标时调用。用于设置子指标、定义线条计算和设置最小周期。

```python
def __init__(self):
    super().__init__()  # 始终先调用 super

# 设置最小周期
    self.addminperiod(self.p.period)

# 创建子指标
    self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)

```

- *重要提示**：始终首先调用 `super().__init__()` 以确保正确的初始化。

### `prenext(self)`

在达到最小周期之前的每根 K 线调用。用于预热计算。

```python
def prenext(self):

# 在预热期间跟踪值
    self._sum += self.data[0]

```

### `nextstart(self)`

首次达到最小周期时调用一次。用于预热后的初始化。

```python
def nextstart(self):

# 使用第一个有效值初始化
    self.lines.value[0] = self._sum / self.p.period

```

### `next(self)`

达到最小周期后的每根 K 线调用。包含主要计算逻辑。

```python
def next(self):

# 计算当前 K 线的指标值
    self.lines.value[0] = self.calculate()

```

### `once(self, start, end)`

批处理计算模式，用于提高性能。在一次调用中处理所有 K 线。

```python
def once(self, start, end):

# 所有 K 线的向量化计算
    src = self.data.array
    dst = self.lines[0].array

    for i in range(start, end):
        dst[i] = self._calculate_at(i)

```
如果只覆盖 `next()` 而不覆盖 `once()`，Backtrader 会自动使用 `next()` 生成 `once()`。

## 最小周期管理

### `addminperiod(self, period)`

增加指标所需的最小周期。

```python
def __init__(self):
    super().__init__()

# 在产生有效输出之前需要 'period' 根 K 线
    self.addminperiod(self.p.period)

```
实际最小周期计算方式：

1. 所有数据源最小周期的最大值
2. 所有子指标最小周期的最大值
3. `addminperiod()` 调用设置的值

## 线条系统使用

### 访问线条

使用点符号或索引访问输出线条：

```python

# 按名称

value = self.indicator.line_name[0]

# 按索引

value = self.indicator.lines[0][0]

# 直接访问（对于单线指标）

value = self.indicator[0]

```

### 历史访问

访问历史值：

```python

# 当前值

current = self.lines.value[0]

# 前一个值

previous = self.lines.value[-1]

# N 个周期前的值

past = self.lines.value[-n]

```

### 设置线条值

在计算方法中设置输出线条值：

```python
def next(self):
    self.lines.value[0] = calculated_value

```

## 指标开发模式

### 模式 1：简单计算

用于不需要状态的简单计算：

```python
class SimpleMA(bt.Indicator):
    lines = ('sma',)
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)

    def next(self):

# 计算最后 'period' 个值的平均值
        sma = sum(self.data[-i] for i in range(self.p.period)) / self.p.period
        self.lines.sma[0] = sma

```

### 模式 2：使用子指标

由其他指标组合成指标：

```python
class CustomOscillator(bt.Indicator):
    lines = ('osc',)
    params = (('fast', 10), ('slow', 20))

    def __init__(self):
        super().__init__()
        self.fast_ma = bt.indicators.SMA(self.data, period=self.p.fast)
        self.slow_ma = bt.indicators.SMA(self.data, period=self.p.slow)

    def next(self):
        self.lines.osc[0] = self.fast_ma[0] - self.slow_ma[0]

```

### 模式 3：多线指标

创建具有多个输出线的指标：

```python
class Bands(bt.Indicator):
    lines = ('mid', 'top', 'bot')
    params = (('period', 20), ('devfactor', 2.0))

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)

    def next(self):

# 计算中轨（SMA）
        mid = sum(self.data[-i] for i in range(self.p.period)) / self.p.period

# 计算标准差
        variance = sum((self.data[-i] - mid) **2 for i in range(self.p.period)) / self.p.period
        stddev = variance** 0.5

# 设置所有线条
        self.lines.mid[0] = mid
        self.lines.top[0] = mid + self.p.devfactor *stddev
        self.lines.bot[0] = mid - self.p.devfactor*stddev

```

### 模式 4：带状态的指标

用于需要在 K 线之间维护状态的指标：

```python
class EMA(bt.Indicator):
    lines = ('ema',)
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)
        self.alpha = 2.0 / (self.p.period + 1)
        self.alpha1 = 1.0 - self.alpha

    def nextstart(self):

# 使用 SMA 种子值
        self.lines.ema[0] = sum(self.data[-i] for i in range(self.p.period)) / self.p.period

    def next(self):

# EMA 公式：EMA(今天) = EMA(昨天)*alpha1 + 价格(今天)*alpha
        self.lines.ema[0] = self.lines.ema[-1]*self.alpha1 + self.data[0]* self.alpha

```

### 模式 5：多数据输入

创建使用多个数据源的指标：

```python
class Spread(bt.Indicator):
    lines = ('spread',)
    _mindatas = 2  # 需要 2 个数据源

    def __init__(self):
        super().__init__()

    def next(self):
        self.lines.spread[0] = self.data0[0] - self.data1[0]

```

## 计算模式

Backtrader 支持两种计算模式：

### next() 模式（默认）

每次计算一根 K 线。实现简单，易于调试。

```python
def next(self):

# 仅计算当前 K 线
    self.lines.value[0] = calculation()

```

### once() 模式（性能）

使用数组操作一次计算所有 K 线。适用于大数据集时更快。

```python
def once(self, start, end):
    src = self.data.array
    dst = self.lines[0].array

    for i in range(start, end):
        dst[i] = calculation(src, i)

```
如果只实现 `next()`，Backtrader 会自动通过每根 K 线调用 `next()` 生成 `once()`。为获得最佳性能，应直接实现 `once()`。

## 指标注册

作为类属性创建的指标会自动注册：

```python
class MyStrategy(bt.Strategy):
    def __init__(self):

# 这些指标会自动注册和计算
        self.sma20 = bt.indicators.SMA(self.data.close, period=20)
        self.sma50 = bt.indicators.SMA(self.data.close, period=50)
        self.crossover = bt.indicators.CrossOver(self.sma20, self.sma50)

    def next(self):
        if self.crossover[0] > 0:
            self.buy()

```

## 内置指标参考

### 移动平均线

| 指标 | 描述 | 参数 |

|-----------|-------------|------------|

| `SMA` | 简单移动平均线 | `period` |

| `EMA` | 指数移动平均线 | `period` |

| `SMMA` | 平滑移动平均线 | `period` |

| `WMA` | 加权移动平均线 | `period` |

| `DEMA` | 双指数移动平均线 | `period` |

| `TEMA` | 三指数移动平均线 | `period` |

| `HMA` | 赫尔移动平均线 | `period` |

| `KAMA` | 考夫曼自适应移动平均线 | `period`, `fast`, `slow` |

### 动量指标

| 指标 | 描述 | 参数 |

|-----------|-------------|------------|

| `RSI` | 相对强弱指数 | `period`, `lookback` |

| `Stochastic` | 随机振荡器 | `period`, `period_dfast` |

| `MACD` | 移动平均收敛发散 | `period_me1`, `period_me2`, `period_signal` |

| `ROC` | 变化率 | `period` |

| `Momentum` | 动量 | `period` |

### 波动率指标

| 指标 | 描述 | 参数 |

|-----------|-------------|------------|

| `ATR` | 平均真实波幅 | `period` |

| `BollingerBands` | 布林带 | `period`, `devfactor` |

| `StandardDeviation` | 标准差 | `period` |

### 趋势指标

| 指标 | 描述 | 参数 |

|-----------|-------------|------------|

| `ADX` | 平均趋向指数 | `period` |

| `Aroon` | 阿隆指标 | `period` |

| `ParabolicSAR` | 抛物线转向 | `af`, `afmax` |

| `Ichimoku` | 一目均衡表 | 多种 |

### 交叉指标

| 指标 | 描述 | 参数 |

|-----------|-------------|------------|

| `CrossOver` | 检测两个方向的交叉（返回 1 或 -1） | 无 |

| `CrossUp` | 仅检测向上交叉 | 无 |

| `CrossDown` | 仅检测向下交叉 | 无 |

### 成交量指标

| 指标 | 描述 | 参数 |

|-----------|-------------|------------|

| `OBV` | 能量潮 | 无 |

| `MFI` | 资金流量指数 | `period` |

## 完整示例：自定义指标

```python
import backtrader as bt

class RelativeVolatility(bt.Indicator):
    """
    自定义指标：相对波动率指数
    衡量相对于自身历史平均值的波动率
    """

    lines = ('rvi',)
    params = (
        ('period', 20),
        ('stddev_period', 20),
    )

    plotinfo = dict(subplot=True)

    def __init__(self):
        super().__init__()
        self.addminperiod(max(self.p.period, self.p.stddev_period))

# 计算滚动标准差
        self.stddev = bt.indicators.StandardDeviation(
            self.data,
            period=self.p.stddev_period
        )

# 计算标准差的滚动平均值
        self.stddev_sma = bt.indicators.SMA(
            self.stddev,
            period=self.p.period
        )

    def next(self):
        current_stddev = self.stddev[0]
        avg_stddev = self.stddev_sma[0]

        if avg_stddev != 0:
            self.lines.rvi[0] = current_stddev / avg_stddev
        else:
            self.lines.rvi[0] = 1.0


class MyStrategy(bt.Strategy):
    def __init__(self):

# 自定义指标
        self.rvi = RelativeVolatility(self.data.close)

# 内置指标
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):

# 使用自定义指标
        if self.rvi[0] > 1.5 and self.data.close[0] > self.sma[0]:
            self.buy()

```

## 绘图配置

### `plotinfo` 选项

| 选项 | 类型 | 描述 |

|--------|------|-------------|

| `subplot` | bool | 在单独的子图中绘制（默认：True） |

| `plotabove` | bool | 在价格图上方绘制 |

| `plotymargin` | float | Y 轴边距 |

| `plothlines` | list | 绘制水平线 |

| `plotyticks` | list | Y 轴刻度值 |

| `_name` | str | 显示名称 |

### `plotlines` 选项

| 选项 | 类型 | 描述 |

|--------|------|-------------|

| `color` | str | 线条颜色 |

| `ls` / `linestyle` | str | 线条样式（'-'、'--'、':'、'.'） |

| `lw` / `linewidth` | float | 线条宽度 |

| `_method` | str | 绘制方法（'line'、'bar'） |

| `_samecolor` | bool | 使用与前一条线相同的颜色 |

| `_name` | str | 线条显示名称 |

## 指标缓存

指标支持缓存以避免重复计算：

```python

# 启用指标缓存

bt.Indicator.usecache(True)

# 清除缓存

bt.Indicator.cleancache()

```

## 常见陷阱

1. **忘记调用 `super().__init__()`**：始终首先调用父类 `__init__`。

2. **最小周期不正确**：使用 `addminperiod()` 指定预热要求。

3. **next() 中的数组访问**：在 `next()` 中使用相对索引（`data[0]`、`data[-1]`），而不是绝对索引。

4. **状态初始化**：使用 `nextstart()` 进行预热后的一次性初始化。

5. **线条命名**：将线条定义为带尾随逗号的元组以表示单条线：`lines = ('value',)`

6. **多个数据源**：当需要多个数据源时设置 `_mindatas`。

## 下一步学习

- [Strategy API](strategy_zh.md) - 在策略中使用指标
- [Data Feeds API](data-feeds_zh.md) - 数据源配置
- [Observer API](observer_zh.md) - 图表观察器和可视化
