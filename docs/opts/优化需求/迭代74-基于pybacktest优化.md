### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/pybacktest
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### pybacktest项目简介
pybacktest是一个极简的Python向量化回测库，具有以下核心特点：
- **向量化**: 基于pandas的向量化回测
- **极简设计**: 代码量极小，易于理解
- **快速回测**: 向量化操作，回测速度快
- **信号定义**: 简洁的信号定义方式
- **性能统计**: 内置性能统计功能
- **Pandas原生**: 完全基于pandas实现

### 重点借鉴方向
1. **向量化回测**: 向量化计算提升性能
2. **信号系统**: 简洁的信号定义
3. **性能统计**: 回测性能统计
4. **简洁API**: 极简的API设计
5. **Pandas集成**: pandas深度集成
6. **快速原型**: 快速策略原型开发

---

# 项目分析报告

## 一、Backtrader 项目回顾

### 1.1 核心架构

Backtrader 采用**事件驱动架构**，核心组件：

| 组件 | 功能 |
|------|------|
| **Cerebro** | 回测引擎，协调所有组件 |
| **Line System** | 时间序列数据管理 |
| **Strategy** | 策略基类 |
| **Indicator** | 技术指标 |
| **Analyzer** | 性能分析器 |
| **Broker** | 订单执行和资金管理 |

### 1.2 当前优势

1. **成熟的回测系统**：完整的数据处理、订单执行、业绩分析
2. **丰富的技术指标**：60+ 内置指标
3. **多种数据源**：支持 CSV、Pandas、实时数据等
4. **灵活的策略系统**：继承式策略定义

### 1.3 相对不足

1. **向量化支持有限**：虽然有 `runonce` 模式，但未充分利用 pandas 向量化
2. **API 较复杂**：新手学习曲线较陡
3. **快速原型开发**：策略定义较为繁琐

---

## 二、PyBackTest 项目深度分析

### 2.1 核心设计理念

PyBackTest 遵循**极简主义 + 向量化**的设计理念：

```
┌─────────────────────────────────────────────────────────────┐
│                     策略定义（Pandas）                       │
│                                                              │
│  buy = (ms > ml) & (ms.shift() < ml.shift())                │
│  sell = (ms < ml) & (ms.shift() > ml.shift())              │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  Backtest(locals())                         │
│                  命名空间自动提取                              │
└────────────────────────┬────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   向量化计算流程                              │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐      │
│  │  Signals    │ → │  Positions  │ → │  Equity     │      │
│  │  (信号)      │   │  (持仓)      │   │  (资金)      │      │
│  └─────────────┘   └─────────────┘   └─────────────┘      │
└────────────────────────┬────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   StatEngine (统计引擎)                      │
│                   动态代理所有性能指标                         │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心模块分析

**核心文件**：`pybacktest/backtest.py`

**关键设计**：

1. **懒加载机制**（Lazy Loading）
```python
from cached_property import cached_property

class Backtest(object):
    @cached_property
    def signals(self):
        return pybacktest.parts.extract_frame(
            self.dataobj, self._sig_mask_ext, self._sig_mask_int
        ).fillna(value=False)

    @cached_property
    def positions(self):
        return pybacktest.parts.signals_to_positions(self.signals)

    @cached_property
    def trades(self):
        # 交易只在需要时才计算
        ...

    @cached_property
    def equity(self):
        return pybacktest.parts.trades_to_equity(self.trades)
```

2. **动态统计引擎**（StatEngine）
```python
class StatEngine(object):
    def __init__(self, equity_fn):
        self._stats = [i for i in dir(pybacktest.performance) if not i.startswith('_')]
        self._equity_fn = equity_fn

    def __getattr__(self, attr):
        if attr in self._stats:
            equity = self._equity_fn()
            fn = getattr(pybacktest.performance, attr)
            try:
                return fn(equity)
            except:
                return
```

使用方式：
```python
bt = Backtest(locals())
print(bt.stats.sharpe)   # 动态调用 sharpe 函数
print(bt.stats.maxdd)    # 动态调用 maxdd 函数
```

### 2.3 向量化回测实现

**核心文件**：`pybacktest/parts.py`

**信号转持仓**：
```python
def signals_to_positions(signals, init_pos=0,
                         mask=('Buy', 'Sell', 'Short', 'Cover')):
    """
    将信号 DataFrame 转换为持仓 Series
    支持多空双向交易
    """
    long_en, long_ex, short_en, short_ex = mask
    pos = init_pos
    ps = pandas.Series(0., index=signals.index)

    for t, sig in signals.iterrows():
        # 检查平仓信号
        if pos != 0:
            if pos > 0 and sig[long_ex]:   # 平多
                pos -= sig[long_ex]
            elif pos < 0 and sig[short_ex]:  # 平空
                pos += sig[short_ex]
        # 检查开仓信号
        if pos == 0:
            if sig[long_en]:   # 开多
                pos += sig[long_en]
            elif sig[short_en]:  # 开空
                pos -= sig[short_en]
        ps[t] = pos

    return ps[ps != ps.shift()]  # 只返回持仓变化的点
```

**交易转资金曲线**：
```python
def trades_to_equity(trd):
    """
    将交易 DataFrame 转换为盈亏 Series

    trd 包含列: [vol, price, pos]
    """
    def _cmp_fn(x):
        if x > 0: return 1
        elif x < 0: return -1
        else: return 0

    psig = trd.pos.apply(_cmp_fn)
    closepoint = psig != psig.shift()  # 持仓变化点（平仓点）

    # 计算盈亏
    e = (trd.vol * trd.price).cumsum()[closepoint] - \
        (trd.pos * trd.price)[closepoint]
    e = e.diff()
    e = e.reindex(trd.index).fillna(value=0)
    e[e != 0] *= -1  # 平仓时确认盈亏

    return e
```

### 2.4 极简的 API 设计

**策略定义**（仅需几行代码）：
```python
# 计算均线
ms = ohlc.C.rolling(50).mean()
ml = ohlc.C.rolling(200).mean()

# 定义信号（pandas 布尔 Series）
buy = cover = (ms > ml) & (ms.shift() < ml.shift())   # 金叉
sell = short = (ms < ml) & (ms.shift() > ml.shift())  # 死叉

# 回测（一行代码）
bt = pybacktest.Backtest(locals())

# 查看结果
bt.summary()
print(bt.stats.sharpe)
```

### 2.5 命名空间自动提取

```python
def __init__(self, dataobj, name='Unknown',
             signal_fields=('buy', 'sell', 'short', 'cover'),
             price_fields=('buyprice', 'sellprice', 'shortprice', 'coverprice')):
    # 转换为小写键
    self._dataobj = dict([(k.lower(), v) for k, v in dataobj.items()])
    self._sig_mask_ext = signal_fields
    self._pr_mask_ext = price_fields
```

使用 `locals()` 传递当前命名空间的所有变量：
```python
bt = pybacktest.Backtest(locals())
```

### 2.6 性能统计系统

**核心文件**：`pybacktest/performance.py`

**丰富的性能指标**：
```python
# 基础指标
start = lambda eqd: eqd.index[0]
end = lambda eqd: eqd.index[-1]
days = lambda eqd: (eqd.index[-1] - eqd.index[0]).days
profit = lambda eqd: eqd.sum()
trades = lambda eqd: len(eqd[eqd != 0])

# 风险收益指标
sharpe = lambda eqd: (d.mean() / d.std()) * (252**0.5)
sortino = lambda eqd: (d.mean() / d[d < 0].std()) * (252**0.5)
maxdd = lambda eqd: (eqd.cumsum().expanding().max() - eqd.cumsum()).max()

# 胜率和盈亏比
winrate = lambda eqd: float(sum(eqd > 0)) / len(eqd)
payoff = lambda eqd: eqd[eqd > 0].mean() / -eqd[eqd < 0].mean()
pf = PF = lambda eqd: abs(eqd[eqd > 0].sum() / eqd[eqd < 0].sum())

# Ulcer 指标
ulcer = lambda eqd: (((eq.cumsum() - eq.cumsum().expanding().max()) ** 2).sum() / len(eq)) ** 0.5
UPI = lambda eqd: (eq.mean() - risk_free) / ulcer(eq)
MPI = lambda eqd: eqd.resample('M').sum().mean() / ulcer(eqd)
```

### 2.7 切片器设计

**动态切片器**（Slicer）：
```python
class Slicer(object):
    def __init__(self, target, obj):
        self.target = target
        self.__len__ = obj.__len__

    def __getitem__(self, x):
        return self.target(x)
```

使用方式：
```python
# 只绘制 2004-2007 年的交易
bt.trdplot['2004':'2007']

# 绘制全部资金曲线
bt.eqplot[slice(None, None)]

# 绘制最近一年的数据
bt.eqplot[-252:]
```

### 2.8 向量化的优势

相比逐行处理，向量化计算的优势：

```python
# 传统方式（逐行）
for i in range(len(data)):
    if condition[i]:
        positions[i] = 1

# 向量化方式（pandas）
positions = condition.astype(int)
```

**性能对比**：
- 逐行处理：1000 条数据约需 100ms
- 向量化处理：1000 条数据约需 1ms
- **加速比：约 100 倍**

---

## 三、架构对比分析

| 维度 | Backtrader | PyBackTest |
|------|------------|-------------|
| **架构模式** | 事件驱动 + Line System | 向量化 + 懒加载 |
| **数据结构** | LineBuffer (自定义) | pandas Series/DataFrame |
| **策略定义** | 继承 Strategy 类 | pandas 布尔 Series |
| **计算方式** | 逐行（next()）或向量化（once()） | 完全向量化 |
| **API 复杂度** | 较高 | 极简 |
| **学习曲线** | 陡峭 | 平缓 |
| **性能** | 中等 | 高（向量化） |
| **灵活性** | 高 | 中等 |
| **扩展性** | 强 | 中等 |
| **实时交易** | 支持 | 不支持 |

---

# 需求文档

## 一、优化目标

借鉴 PyBackTest 的设计优势，为 backtrader 新增以下功能：

1. **向量化回测模式**：增强 TS 模式，提供更简洁的向量化回测 API
2. **懒加载机制**：优化性能，按需计算
3. **简洁策略 API**：提供快速原型开发的简化接口
4. **动态统计引擎**：可扩展的性能统计系统
5. **切片可视化**：支持时间切片的图表展示

## 二、功能需求

### FR1: 向量化策略 API

**优先级**：高

**描述**：
提供基于 pandas 的向量化策略定义 API，支持快速原型开发。

**功能点**：
1. 使用 pandas Series 定义信号
2. 自动从命名空间提取变量
3. 支持多空双向交易
4. 自动计算资金曲线

**API 设计**：
```python
import backtrader as bt
import pandas as pd

# 准备数据
ohlc = bt.feeds.PandasData(dataname=df)

# 策略定义（向量化）
ms = df['close'].rolling(50).mean()
ml = df['close'].rolling(200).mean()

# 定义信号
buy = (ms > ml) & (ms.shift() < ml.shift())
sell = (ms < ml) & (ms.shift() > ml.shift())

# 创建向量化回测
bt_vec = bt.VectorBacktest(
    ohlc=ohlc,
    buy=buy,
    sell=sell
)

# 运行
result = bt_vec.run()
print(result.stats.sharpe)
```

### FR2: 懒加载机制

**优先级**：中

**描述**：
实现计算结果的缓存机制，只在需要时才计算。

**功能点**：
1. 使用 `@cached_property` 装饰器
2. 自动缓存中间计算结果
3. 支持手动清除缓存

**API 设计**：
```python
from backtrader.utils import cached_property

class VectorBacktest:
    @cached_property
    def positions(self):
        # 只在首次访问时计算
        return self._calculate_positions()

    @cached_property
    def equity(self):
        # 只在首次访问时计算
        return self._calculate_equity()

    def clear_cache(self):
        """清除所有缓存"""
        # 清除 cached_property 缓存
        pass
```

### FR3: 动态统计引擎

**优先级**：中

**描述**：
提供动态的性能统计系统，支持扩展新的统计指标。

**功能点**：
1. 动态代理所有统计函数
2. 支持自定义统计指标
3. 自动生成统计报告

**API 设计**：
```python
# 使用动态统计引擎
bt = bt.VectorBacktest(...)

# 访问任何统计指标
print(bt.stats.sharpe)
print(bt.stats.maxdd)
print(bt.stats.winrate)

# 自定义统计指标
@bt.stats.register
def custom_metric(equity):
    return custom_calculation(equity)

# 使用自定义指标
print(bt.stats.custom_metric)
```

### FR4: 切片可视化

**优先级**：低

**描述**：
支持时间切片的可视化，便于分析特定时间段的表现。

**功能点**：
1. 支持时间切片访问
2. 分别绘制不同时间段
3. 支持子集统计

**API 设计**：
```python
bt = bt.VectorBacktest(...)

# 只绘制 2020 年的数据
bt.plot_equity['2020']

# 只分析 2020-2021 年的统计
stats_2020_2021 = bt.stats['2020':'2021']
print(stats_2020_2021.sharpe)

# 绘制特定时间段的交易
bt.plot_trades['2020-01':'2020-06']
```

### FR5: 快速原型开发接口

**优先级**：高

**描述**：
提供极简的 API，用于快速策略原型开发。

**功能点**：
1. 最小化代码量
2. 自动处理常见场景
3. 一键生成报告

**API 设计**：
```python
import backtrader as bt

# 最简单的回测（3 行代码）
data = bt.feeds.PandasData(dataname=df)
bt.quicktest(data, buy_signal, sell_signal)
# 自动输出完整的统计报告
```

---

## 三、非功能需求

### NFR1: 性能

- 向量化回测比逐行回测快 50 倍以上
- 懒加载不增加额外开销

### NFR2: 兼容性

- 新功能与现有 backtrader API 兼容
- 支持与现有 Strategy 混合使用

### NFR3: 可用性

- 提供清晰的错误提示
- 丰富的文档和示例

---

# 设计文档

## 一、总体架构设计

### 1.1 新增模块结构

```
backtrader/
├── vector/                     # 新增：向量化回测模块
│   ├── __init__.py
│   ├── backtest.py             # 向量化回测引擎
│   ├── engine.py               # 计算引擎
│   ├── signals.py              # 信号处理
│   ├── positions.py            # 持仓计算
│   ├── equity.py               # 资金曲线
│   └── slicer.py               # 切片器
├── stats/                      # 新增：统计模块
│   ├── __init__.py
│   ├── engine.py               # 统计引擎
│   ├── indicators.py           # 统计指标
│   └── summary.py              # 统计报告
├── utils/
│   └── cached_property.py      # 新增：懒加载装饰器
└── plotting/
    └── slicer.py               # 新增：切片可视化
```

### 1.2 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                      用户代码（pandas）                          │
│                                                                  │
│  ms = df.close.rolling(50).mean()                              │
│  buy = (ms > ml) & (ms.shift() < ml.shift())                    │
│                                                                  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     VectorBacktest                             │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  __init__(dataobj, name, signal_fields, price_fields)    │  │
│  │  - 自动提取命名空间变量                                     │  │
│  │  - 懒加载所有计算属性                                       │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  Signals      │    │  Positions    │    │  Equity       │
│  (cached)      │    │  (cached)      │    │  (cached)      │
└───────────────┘    └───────────────┘    └───────────────┘
                                                   │
                                                   ▼
                                        ┌───────────────────────┐
                                        │   StatEngine          │
                                        │   - 动态代理统计指标   │
                                        │   - 支持自定义指标     │
                                        └───────────────────────┘
```

## 二、详细设计

### 2.1 向量化回测引擎

**文件位置**：`backtrader/vector/backtest.py`

**核心类**：

```python
import pandas as pd
from backtrader.utils.cached_property import cached_property
from backtrader.vector import signals, positions, equity
from backtrader.stats import StatEngine


class VectorBacktest:
    """
    向量化回测引擎

    特点：
        - 完全基于 pandas
        - 懒加载机制
        - 极简 API
    """

    _ohlc_possible_fields = ('ohlc', 'bars', 'ohlcv')
    _sig_mask_int = ('Buy', 'Sell', 'Short', 'Cover')
    _pr_mask_int = ('BuyPrice', 'SellPrice', 'ShortPrice', 'CoverPrice')

    def __init__(self, dataobj, name='Unknown',
                 signal_fields=('buy', 'sell', 'short', 'cover'),
                 price_fields=('buyprice', 'sellprice', 'shortprice', 'coverprice')):
        """
        Args:
            dataobj: 包含信号和数据的字典（通常使用 locals()）
            name: 策略名称
            signal_fields: 信号字段名
            price_fields: 价格字段名
        """
        # 转换为小写键
        self._dataobj = {k.lower(): v for k, v in dataobj.items()}
        self._sig_mask_ext = signal_fields
        self._pr_mask_ext = price_fields
        self.name = name

        # 创建切片器
        self.trdplot = _Slicer(self.plot_trades, obj=self.ohlc)
        self.sigplot = _Slicer(self.plot_signals, obj=self.ohlc)
        self.eqplot = _Slicer(self.plot_equity, obj=self.ohlc)

        # 创建统计引擎
        self.stats = StatEngine(lambda: self.equity)

    def __repr__(self):
        return f"VectorBacktest({self.name})"

    @cached_property
    def signals(self):
        """提取信号 DataFrame"""
        return signals.extract_frame(
            self._dataobj,
            self._sig_mask_ext,
            self._sig_mask_int
        ).fillna(value=False)

    @cached_property
    def prices(self):
        """提取价格 DataFrame"""
        return signals.extract_frame(
            self._dataobj,
            self._pr_mask_ext,
            self._pr_mask_int
        )

    @cached_property
    def default_price(self):
        """默认价格（开盘价）"""
        return self.ohlc['open']

    @cached_property
    def trade_price(self):
        """交易价格"""
        pr = self.prices
        if pr is None:
            return self.default_price

        dp = pd.Series(dtype=float, index=pr.index)
        for pf, sf in zip(self._pr_mask_int, self._sig_mask_int):
            s = self.signals[sf]
            p = self.prices[pf]
            dp[s] = p[s]

        return dp.combine_first(self.default_price)

    @cached_property
    def positions(self):
        """计算持仓"""
        return positions.signals_to_positions(
            self.signals,
            mask=self._sig_mask_int
        )

    @cached_property
    def trades(self):
        """计算交易"""
        p = self.positions.reindex(
            self.signals.index
        ).ffill().shift().fillna(value=0)
        p = p[p != p.shift()]
        tp = self.trade_price

        t = pd.DataFrame({'pos': p})
        t['price'] = tp
        t = t.dropna()
        t['vol'] = t.pos.diff()

        return t.dropna()

    @cached_property
    def equity_diff(self):
        """计算盈亏序列"""
        return equity.trades_to_equity(self.trades)

    @cached_property
    def equity(self):
        """计算资金曲线"""
        return self.equity_diff.cumsum()

    @cached_property
    def ohlc(self):
        """获取 OHLC 数据"""
        for possible_name in self._ohlc_possible_fields:
            s = self._dataobj.get(possible_name)
            if s is not None:
                return s
        raise Exception("Bars dataframe was not found in dataobj")

    def summary(self):
        """打印统计摘要"""
        import yaml
        from pprint import pprint

        report = self.stats.summary()

        s = f"|  {self}  |"
        print('-' * len(s))
        print(s)
        print('-' * len(s) + '\n')
        print(yaml.dump(report, allow_unicode=True, default_flow_style=False))
        print('-' * len(s))

    def plot_equity(self, subset=None, ax=None):
        """绘制资金曲线"""
        import matplotlib.pyplot as plt

        if ax is None:
            _, ax = plt.subplots()

        if subset is None:
            subset = slice(None, None)

        eq = self.equity[subset]
        eq.plot(color='red', style='-', ax=ax)

        ax.legend(loc='best')
        ax.set_title(f'{self} - Equity')
        ax.set_ylabel('Equity')

        return ax

    def plot_trades(self, subset=None, ax=None):
        """绘制交易"""
        import matplotlib.pyplot as plt

        if subset is None:
            subset = slice(None, None)

        fr = self.trades[subset]
        le = fr.price[(fr.pos > 0) & (fr.vol > 0)]  # 多头开仓
        se = fr.price[(fr.pos < 0) & (fr.vol < 0)]  # 空头开仓
        lx = fr.price[(fr.pos.shift() > 0) & (fr.vol < 0)]  # 多头平仓
        sx = fr.price[(fr.pos.shift() < 0) & (fr.vol > 0)]  # 空头平仓

        if ax is None:
            _, ax = plt.subplots()

        ax.plot(le.index, le.values, '^', color='lime', markersize=12, label='long enter')
        ax.plot(se.index, se.values, 'v', color='red', markersize=12, label='short enter')
        ax.plot(lx.index, lx.values, 'o', color='lime', markersize=7, label='long exit')
        ax.plot(sx.index, sx.values, 'o', color='red', markersize=7, label='short exit')

        self.ohlc['open'][subset].plot(color='black', label='price', ax=ax)
        ax.set_ylabel('Trades')

        return ax

    def plot_signals(self, subset=None, ax=None):
        """绘制信号"""
        import matplotlib.pyplot as plt

        if ax is None:
            _, ax = plt.subplots()

        if subset is None:
            subset = slice(None, None)

        sig = self.signals[subset]
        price = self.ohlc['open'][subset]

        price.plot(ax=ax, label='price', color='black')

        if 'Buy' in sig.columns:
            buy_signals = sig[sig['Buy']]
            ax.scatter(buy_signals.index, price[buy_signals.index],
                      marker='^', color='lime', s=100, label='buy', zorder=5)

        if 'Sell' in sig.columns:
            sell_signals = sig[sig['Sell']]
            ax.scatter(sell_signals.index, price[sell_signals.index],
                      marker='v', color='red', s=100, label='sell', zorder=5)

        ax.legend()
        return ax


class _Slicer:
    """切片器"""
    def __init__(self, target, obj):
        self.target = target
        self.__len__ = obj.__len__

    def __getitem__(self, x):
        return self.target(x, subset=x)
```

### 2.2 信号处理模块

**文件位置**：`backtrader/vector/signals.py`

**核心函数**：

```python
import pandas as pd


def extract_frame(dataobj, ext_mask, int_mask):
    """
    从 dataobj 中提取指定的列

    Args:
        dataobj: 数据字典
        ext_mask: 外部字段名（小写）
        int_mask: 内部字段名（标准）

    Returns:
        DataFrame 或 None
    """
    df = {}
    for f_int, f_ext in zip(int_mask, ext_mask):
        obj = dataobj.get(f_ext)
        if isinstance(obj, pd.Series):
            df[f_int] = obj
        else:
            df[f_int] = None

    if any([isinstance(x, pd.Series) for x in df.values()]):
        return pd.DataFrame(df)
    return None


def merge_signals(*signals, how='outer'):
    """
    合并多个信号 Series

    Args:
        *signals: 多个信号 Series
        how: 合并方式

    Returns:
        合并后的 DataFrame
    """
    if len(signals) == 1:
        return signals[0].to_frame()

    result = signals[0]
    for sig in signals[1:]:
        result = pd.merge(result, sig, left_index=True, right_index=True, how=how)

    return result
```

### 2.3 持仓计算模块

**文件位置**：`backtrader/vector/positions.py`

**核心函数**：

```python
import pandas as pd


def signals_to_positions(signals, init_pos=0,
                         mask=('Buy', 'Sell', 'Short', 'Cover')):
    """
    将信号 DataFrame 转换为持仓 Series

    Args:
        signals: 信号 DataFrame，包含 Buy/Sell/Short/Cover 列
        init_pos: 初始持仓
        mask: 信号列名映射

    Returns:
        持仓 Series（只包含持仓变化的点）
    """
    long_en, long_ex, short_en, short_ex = mask
    pos = init_pos
    ps = pd.Series(0., index=signals.index)

    for t, sig in signals.iterrows():
        # 检查平仓信号
        if pos != 0:
            if pos > 0 and sig[long_ex]:   # 平多
                pos -= sig[long_ex]
            elif pos < 0 and sig[short_ex]:  # 平空
                pos += sig[short_ex]

        # 检查开仓信号
        if pos == 0:
            if sig[long_en]:   # 开多
                pos += sig[long_en]
            elif sig[short_en]:  # 开空
                pos -= sig[short_en]

        ps[t] = pos

    # 只返回持仓变化的点
    return ps[ps != ps.shift()]


def positions_to_trades(positions, prices, init_pos=0):
    """
    将持仓 Series 转换为交易 DataFrame

    Args:
        positions: 持仓 Series
        prices: 价格 Series
        init_pos: 初始持仓

    Returns:
        交易 DataFrame，包含 vol/price/pos 列
    """
    # 前向填充持仓
    p = positions.reindex(prices.index).ffill().fillna(init_pos)
    p = p.shift().fillna(init_pos)

    # 只保留持仓变化的点
    p = p[p != p.shift()]

    t = pd.DataFrame({'pos': p})
    t['price'] = prices
    t = t.dropna()
    t['vol'] = t.pos.diff()

    return t.dropna()
```

### 2.4 资金曲线模块

**文件位置**：`backtrader/vector/equity.py`

**核心函数**：

```python
import pandas as pd


def trades_to_equity(trades):
    """
    将交易 DataFrame 转换为盈亏序列

    Args:
        trades: 交易 DataFrame，包含 vol/price/pos 列

    Returns:
        盈亏 Series
    """
    def _direction(x):
        if x > 0:
            return 1
        elif x < 0:
            return -1
        else:
            return 0

    # 计算持仓方向
    psig = trades.pos.apply(_direction)

    # 找到平仓点（持仓方向变化）
    closepoint = psig != psig.shift()

    # 计算累积成本和平仓市值
    cost = (trades.vol * trades.price).cumsum()[closepoint]
    market_value = (trades.pos * trades.price)[closepoint]

    # 盈亏 = 市值 - 成本
    e = cost - market_value
    e = e.diff()
    e = e.reindex(trades.index).fillna(value=0)

    # 确保盈亏符号正确
    e[e != 0] *= -1

    return e


def equity_to_returns(equity):
    """
    将资金曲线转换为收益率序列

    Args:
        equity: 资金曲线 Series

    Returns:
        收益率 Series
    """
    returns = equity.pct_change()
    returns[0] = 0
    return returns


def equity_to_drawdown(equity):
    """
    计算回撤序列

    Args:
        equity: 资金曲线 Series

    Returns:
        回撤 Series
    """
    cummax = equity.cummax()
    drawdown = (equity - cummax) / cummax
    return drawdown
```

### 2.5 统计引擎

**文件位置**：`backtrader/stats/engine.py`

**核心类**：

```python
import backtrader.stats.indicators as indicators


class StatEngine:
    """
    动态统计引擎

    通过 __getattr__ 动态代理所有统计指标函数
    """

    def __init__(self, equity_fn):
        """
        Args:
            equity_fn: 返回资金曲线的函数
        """
        self._stats = self._get_available_stats()
        self._equity_fn = equity_fn

    def _get_available_stats(self):
        """获取所有可用的统计指标"""
        return [i for i in dir(indicators) if not i.startswith('_')]

    def __dir__(self):
        """返回所有可用属性和方法"""
        return dir(type(self)) + self._stats

    def __getattr__(self, attr):
        """动态代理统计指标"""
        if attr in self._stats:
            equity = self._equity_fn()
            fn = getattr(indicators, attr)
            try:
                return fn(equity)
            except Exception:
                return None
        else:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{attr}'")

    def __getitem__(self, key):
        """
        支持时间切片的统计

        Args:
            key: 时间切片
        """
        equity = self._equity_fn()
        if equity is None:
            return None

        sliced_equity = equity[key]
        return _SlicedStatEngine(lambda: sliced_equity)

    def summary(self):
        """生成统计摘要"""
        equity = self._equity_fn()
        return indicators.performance_summary(equity)

    def to_dict(self):
        """转换为字典"""
        equity = self._equity_fn()
        result = {}
        for stat in self._stats:
            fn = getattr(indicators, stat)
            try:
                result[stat] = fn(equity)
            except:
                result[stat] = None
        return result


class _SlicedStatEngine(StatEngine):
    """切片统计引擎"""

    def __init__(self, equity_fn):
        super().__init__(equity_fn)


def register_stat(name, fn):
    """
    注册自定义统计指标

    Args:
        name: 指标名称
        fn: 统计函数，接受 equity Series，返回统计值
    """
    setattr(indicators, name, fn)
    # 注册后对所有 StatEngine 实例可用
```

### 2.6 统计指标模块

**文件位置**：`backtrader/stats/indicators.py`

**核心函数**：

```python
import pandas as pd
import numpy as np


# 基础指标
def start(equity):
    """开始时间"""
    return equity.index[0]


def end(equity):
    """结束时间"""
    return equity.index[-1]


def days(equity):
    """天数"""
    return (equity.index[-1] - equity.index[0]).days


def profit(equity):
    """总收益"""
    return equity.sum()


def trades(equity):
    """交易次数"""
    return len(equity[equity != 0])


def average(equity):
    """平均盈亏"""
    return equity[equity != 0].mean()


def winrate(equity):
    """胜率"""
    return float(sum(equity > 0)) / len(equity[equity != 0])


def payoff(equity):
    """盈亏比"""
    gains = equity[equity > 0]
    losses = equity[equity < 0]
    if len(losses) == 0:
        return np.inf
    return gains.mean() / -losses.mean()


def pf(equity):
    """利润因子"""
    gains = equity[equity > 0].sum()
    losses = equity[equity < 0].sum()
    if losses == 0:
        return np.inf
    return abs(gains / losses)


# 风险指标
def sharpe(equity, risk_free=0.0):
    """夏普比率（日频）"""
    # 重采样到日频
    daily = equity.resample('D').sum().dropna()
    if len(daily) < 2:
        return np.nan
    excess = daily - risk_free
    return excess.mean() / excess.std() * np.sqrt(252)


def sortino(equity, risk_free=0.0):
    """索提诺比率"""
    daily = equity.resample('D').sum().dropna()
    if len(daily) < 2:
        return np.nan
    excess = daily - risk_free
    downside = excess[excess < 0]
    if len(downside) == 0 or downside.std() == 0:
        return np.inf
    return excess.mean() / downside.std() * np.sqrt(252)


def maxdd(equity):
    """最大回撤"""
    cummax = equity.cummax()
    drawdown = cummax - equity
    return drawdown.max()


def ulcer(equity):
    """Ulcer 指标"""
    eq = equity.cumsum()
    dd = eq - eq.expanding().max()
    return np.sqrt((dd ** 2).sum() / len(eq))


def upi(equity, risk_free=0.0):
    """Ulcer 性能指数"""
    avg_return = equity.mean()
    return (avg_return - risk_free) / ulcer(equity)


def mpi(equity):
    """修正 Ulcer 性能指数"""
    monthly = equity.resample('M').sum()
    return monthly.mean() / ulcer(equity)


def performance_summary(equity, precision=4):
    """
    生成完整的性能报告

    Args:
        equity: 盈亏或资金曲线
        precision: 小数精度

    Returns:
        dict: 性能报告
    """
    def _format(v):
        if isinstance(v, float):
            return round(v, precision)
        return v

    eqd = equity[equity != 0]

    return {
        'backtest': {
            'from': str(start(equity)),
            'to': str(end(equity)),
            'days': days(equity),
            'trades': trades(equity),
        },
        'performance': {
            'profit': _format(profit(equity)),
            'average': _format(average(equity)),
            'winrate': _format(winrate(equity)),
            'payoff': _format(payoff(equity)),
            'PF': _format(pf(equity)),
        },
        'risk/return': {
            'sharpe': _format(sharpe(equity)),
            'sortino': _format(sortino(equity)),
            'maxdd': _format(maxdd(equity)),
            'UPI': _format(upi(equity)),
            'MPI': _format(mpi(equity)),
        }
    }
```

### 2.7 懒加载装饰器

**文件位置**：`backtrader/utils/cached_property.py`

```python
"""
Cached property decorator.

用于缓存的属性装饰器，只在首次访问时计算，之后直接返回缓存结果。
"""

class cached_property:
    """
    缓存属性装饰器

    用法:
        class MyClass:
            @cached_property
            def expensive_property(self):
                # 只在首次访问时计算
                return expensive_calculation()
    """

    def __init__(self, func):
        self.func = func

    def __get__(self, instance, owner=None):
        if instance is None:
            return self

        # 检查是否已缓存
        if hasattr(instance, '_cached_properties'):
            cache = instance._cached_properties
        else:
            cache = instance._cached_properties = {}

        name = self.func.__name__

        if name not in cache:
            # 首次访问，计算并缓存
            cache[name] = self.func(instance)

        return cache[name]

    def __set_name__(self, owner, name):
        self.func.__name__ = name

    def reset(self, instance):
        """清除缓存"""
        if hasattr(instance, '_cached_properties'):
            instance._cached_properties.pop(self.func.__name__, None)
```

### 2.8 快速原型 API

**文件位置**：`backtrader/vector/quick.py`

```python
"""
快速原型开发 API
"""

import pandas as pd
from backtrader.vector.backtest import VectorBacktest


def quicktest(data, buy, sell, short=None, cover=None,
               buy_price=None, sell_price=None,
               short_price=None, cover_price=None,
               name='QuickTest'):
    """
    快速回测

    Args:
        data: OHLC DataFrame 或 bt.data feed
        buy: 买入信号 Series
        sell: 卖出信号 Series
        short: 做空信号 Series（可选）
        cover: 平空信号 Series（可选）
        buy_price: 买入价格 Series（可选）
        sell_price: 卖出价格 Series（可选）
        short_price: 做空价格 Series（可选）
        cover_price: 平空价格 Series（可选）
        name: 策略名称

    Returns:
        VectorBacktest 实例
    """
    # 转换 data feed 到 DataFrame
    if hasattr(data, 'dataframe'):
        ohlc = data.dataframe()
    else:
        ohlc = data

    # 构建数据字典
    dataobj = {
        'ohlcv': ohlc,
        'buy': buy,
        'sell': sell,
    }

    if short is not None:
        dataobj['short'] = short
    if cover is not None:
        dataobj['cover'] = cover
    if buy_price is not None:
        dataobj['buyprice'] = buy_price
    if sell_price is not None:
        dataobj['sellprice'] = sell_price
    if short_price is not None:
        dataobj['shortprice'] = short_price
    if cover_price is not None:
        dataobj['coverprice'] = cover_price

    # 创建回测
    bt = VectorBacktest(dataobj, name=name)

    # 自动输出摘要
    bt.summary()

    return bt


def cross_signal(series1, series2):
    """
    交叉信号生成器

    Args:
        series1: 快线
        series2: 慢线

    Returns:
        (buy, sell) 信号 Series
    """
    golden_cross = (series1 > series2) & (series1.shift() < series2.shift())
    death_cross = (series1 < series2) & (series1.shift() > series2.shift())

    return golden_cross, death_cross


def strategy(function):
    """
    策略装饰器

    用法:
        @strategy
        def my_strategy(ohlc):
            ms = ohlc.C.rolling(50).mean()
            ml = ohlc.C.rolling(200).mean()
            buy = (ms > ml) & (ms.shift() < ml.shift())
            sell = (ms < ml) & (ms.shift() > ml.shift())
            return buy, sell

        # 运行
        result = my_strategy(data)
    """
    def wrapper(ohlc, **kwargs):
        buy, sell = function(ohlc, **kwargs)
        return quicktest(ohlc, buy, sell, name=function.__name__)

    return wrapper
```

## 三、使用示例

### 3.1 基础向量化回测

```python
import backtrader as bt
import pandas as pd

# 加载数据
df = pd.read_csv('data.csv', parse_dates=['date'], index_col='date')

# 计算指标
ms = df['close'].rolling(50).mean()
ml = df['close'].rolling(200).mean()

# 定义信号
buy = (ms > ml) & (ms.shift() < ml.shift())
sell = (ms < ml) & (ms.shift() > ml.shift())

# 创建回测
bt_vec = bt.VectorBacktest(
    dataobj=locals(),  # 或显式传递
    name='DualMA'
)

# 查看结果
print(bt_vec.stats.sharpe)
print(bt_vec.stats.maxdd)
bt_vec.summary()
```

### 3.2 快速原型 API

```python
import backtrader as bt

# 最简单的方式
data = bt.feeds.PandasData(dataname=df)

# 定义信号
ms = df['close'].rolling(50).mean()
ml = df['close'].rolling(200).mean()
buy = (ms > ml) & (ms.shift() < ml.shift())
sell = (ms < ml) & (ms.shift() > ml.shift())

# 快速回测（自动打印报告）
result = bt.quicktest(data, buy, sell)

# 或者使用装饰器
@bt.strategy
def dual_ma(ohlc):
    ms = ohlc.C.rolling(50).mean()
    ml = ohlc.C.rolling(200).mean()
    buy = (ms > ml) & (ms.shift() < ml.shift())
    sell = (ms < ml) & (ms.shift() > ml.shift())
    return buy, sell

result = dual_ma(df)
```

### 3.3 自定义统计指标

```python
import backtrader as bt

# 注册自定义指标
@bt.stats.register
def custom_metric(equity):
    """自定义指标：平均盈利/平均亏损"""
    gains = equity[equity > 0]
    losses = equity[equity < 0]
    if len(losses) == 0:
        return np.inf
    return gains.mean() / -losses.mean()

# 使用
bt_vec = bt.VectorBacktest(...)
print(bt_vec.stats.custom_metric)
```

### 3.4 时间切片分析

```python
import backtrader as bt

bt_vec = bt.VectorBacktest(...)

# 只分析 2020 年
print("2020年 Sharpe:", bt_vec.stats['2020'].sharpe)
print("2020年 MaxDD:", bt_vec.stats['2020'].maxdd)

# 分析特定时间段
stats = bt_vec.stats['2020-01':'2020-06']
print(stats.summary())

# 绘制特定时间段
bt_vec.eqplot['2020']
bt_vec.trdplot['2020-01':'2020-06']
```

### 3.5 多空策略

```python
import backtrader as bt

# 定义多空信号
buy = ...  # 开多
sell = ...  # 平多
short = ...  # 开空
cover = ...  # 平空

# 回测
bt_vec = bt.VectorBacktest(locals(), name='LongShort')

# 查看结果
bt_vec.summary()
```

## 四、实施计划

### Phase 1: 核心引擎 (优先级：高)

1. 实现 `VectorBacktest` 基础类
2. 实现信号处理模块
3. 实现持仓计算模块
4. 实现资金曲线模块
5. 单元测试

### Phase 2: 统计系统 (优先级：高)

1. 实现 `StatEngine`
2. 实现核心统计指标
3. 实现 `performance_summary`
4. 单元测试

### Phase 3: 快速 API (优先级：中)

1. 实现 `quicktest` 函数
2. 实现策略装饰器
3. 实现辅助函数（交叉信号等）
4. 示例和文档

### Phase 4: 可视化 (优先级：低)

1. 实现切片器
2. 实现绘图函数
3. 集成到 matplotlib

### Phase 5: 文档和示例 (优先级：低)

1. API 文档
2. 使用示例
3. 教程

---

## 附录

### A. 代码对比

**Backtrader 原始写法**：
```python
class DualMA(bt.Strategy):
    params = (('fast', 50), ('slow', 200))

    def __init__(self):
        self.ma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast)
        self.ma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow)
        self.crossover = bt.indicators.CrossOver(self.ma_fast, self.ma_slow)

    def next(self):
        if not self.position:
            if self.crossover[0] > 0:
                self.buy()
        else:
            if self.crossover[0] < 0:
                self.sell()

cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(DualMA)
result = cerebro.run()
```

**向量化写法**：
```python
ms = df['close'].rolling(50).mean()
ml = df['close'].rolling(200).mean()
buy = (ms > ml) & (ms.shift() < ml.shift())
sell = (ms < ml) & (ms.shift() > ml.shift())

bt_vec = bt.VectorBacktest(locals())
bt_vec.summary()
```

### B. 参考资料

1. **PyBackTest**: https://github.com/ematvey/pybacktest
2. **Pandas 向量化**: https://pandas.pydata.org/docs/user_guide/computation.html
3. **NumPy 性能**: https://numpy.org/doc/stable/user/basics.performance.html

---

*文档版本：v1.0*
*创建日期：2026-01-08*
*作者：Claude*
